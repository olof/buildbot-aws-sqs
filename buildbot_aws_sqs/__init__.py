import boto3
from zope.interface import implementer
from twisted.internet import defer, threads
from twisted.application.internet import TimerService
from twisted.python import log
from buildbot.util import ComparableMixin
from buildbot.util.service import BuildbotService
from buildbot.interfaces import IChangeSource


class SQSPollingService(BuildbotService):
    """
    Polling service to get messages from AWS Simple Queue Service (SQS).

    Inspired by the MaildirService class from buildbot.util.service.
    """
    def __init__(self, uri, pollinterval=60, codebase=None,
                 aws_region='eu-central-1', **kwargs):
        """
        Takes an uri to the SQS queue.

        It also, optionally, takes a pollinterval (seconds between polls).
        Defaults to 60. For cost estimate: free tier is one million requests
        per month. After that, it's $0.40/million requests. If we poll every
        minute, we'll do about 44000 requests.

        We'll utilize "long polling", where we connect to SQS and leave the
        connection open in case new messages arrive. The AWS max timeout for
        this connection is 20s. This means that we sometime have to wait 40s
        to see a message.

        Maybe a recommended value could be 20? That would mean about 131000
        requests/month. Having a higher default pollinterval value is a
        cautious choice, but can increase latency for some messages.
        """
        super().__init__(**kwargs)
        self.pollinterval = pollinterval
        self.uri = uri
        self.aws_region = aws_region
        self.sqs = boto3.client("sqs", region_name=aws_region)
        self.default_codebase = codebase

    def startService(self):
        self.timerService = TimerService(self.pollinterval, self.poll)
        self.timerService.setServiceParent(self)
        return super().startService()

    def stopService(self):
        self.timerService.disownServiceParent()
        self.timerService = None
        return super().stopService()

    def _get_sqs_msg(self):
        return self.sqs.receive_message(
            QueueUrl=self.uri,
            AttributeNames=['SentTimestamp'],
            WaitTimeSeconds=20,
        )

    def is_empty(self, resp):
        # In practice, "no messages avilable" will get you a response
        # *without* a Messages key. Out of caution, we also handle the
        # Messages key being an empty list.
        # {
        #   'ResponseMetadata': {
        #     'RequestId': '19999999-7999-5999-8999-a99999999999',
        #     'HTTPStatusCode': 200,
        #     'HTTPHeaders': {
        #       'x-amzn-requestid': '19999999-7999-5999-8999-a99999999999',
        #       'date': 'Tue, 12 Nov 2019 18:44:13 GMT',
        #       'content-type': 'text/xml',
        #       'content-length': '240'
        #     },
        #     'RetryAttempts': 0
        #   }
        # }
        return 'Messages' not in resp or not resp['Messages']

    @defer.inlineCallbacks
    def sqs_poll(self):
        log.msg("Polling SQS queue %s" % self.uri)
        resp = yield threads.deferToThread(self._get_sqs_msg)

        log.msg("Poll result SQS queue %s: %s" % (self.uri, resp))

        if self.is_empty(resp):
            defer.returnValue(None)

        # Structure of a response with messages available:
        # {
        #   'Messages': [
        #     {
        #       'MessageId': 'b9999999-4999-4999-8999-d99999999999',
        #       'ReceiptHandle': 'AAAAAaaaAa....,',
        #       'MD5OfBody': '4b39812e2d7f14f01ae86e7e5bb417d6',
        #       'Body': '{"foo": "bar", "baz": "qux"}',
        #       'Attributes': {
        #         'SentTimestamp': '1573477920399'
        #       }
        #     }
        #   ],
        #   'ResponseMetadata': {
        #     'RequestId': 'd9999999-b999-5999-b999-89999999999b',
        #     'HTTPStatusCode': 200,
        #     'HTTPHeaders': {
        #       'x-amzn-requestid': 'd9999999-b999-5999-b999-89999999999b',
        #       'date': 'Mon, 11 Nov 2019 13:12:00 GMT',
        #       'content-type': 'text/xml',
        #       'content-length': '996'
        #     },
        #     'RetryAttempts': 0
        #   }
        # }

        # TODO support popping multiple messages? Today, we only ask
        # for one message, but we can ask for up to 10 at a time. We
        # could thus generate ten changes per poll.
        defer.returnValue(resp['Messages'][0])

    def delete_msg(self, msg):
        self.sqs.delete_message(
            QueueUrl=self.uri,
            ReceiptHandle=msg['ReceiptHandle']
        )

    def handleMessage(self, msg):
        raise NotImplementedError

    @defer.inlineCallbacks
    def poll(self):
        msg = yield self.sqs_poll()
        if msg:
            yield self.handleMessage(msg)
            self.delete_msg(msg)


@implementer(IChangeSource)
class SQSSource(SQSPollingService, ComparableMixin):
    """
    This is a ChangeSource where you can subscribe to an AWS SQS queue.
    Each message sent to the queue will create a new change in buildbot.
    The change will have the property "sqs_body" set to the sqs message
    body.

    Inspired by the MaildirSource class from buildbot.changes.mail.
    """
    compare_attrs = ('uri', 'pollinterval')
    name = 'SQSSource'

    def msg_project(self, msg):
        return None

    def msg_comment(self, msg):
        return 'sqs'

    def msg_author(self, msg):
        return 'sqs'

    def msg_revision(self, msg):
        return msg['MessageId']

    def msg_timestamp(self, msg):
        return int(msg['Attributes']['SentTimestamp']) / 1000

    def msg_properties(self, msg):
        return {
            'sqs_body': msg['Body'],
        }

    def msg_repository(self, msg):
        return self.uri

    def msg_branch(self, msg):
        return ''

    def msg_codebase(self, msg):
        return self.default_codebase

    def msg_to_change(self, msg):
        return {
            'src': 'sqs',
            'codebase': self.msg_codebase(msg),
            'repository': self.msg_repository(msg),
            'project': self.msg_project(msg),
            'branch': self.msg_branch(msg),
            'author': self.msg_author(msg),
            'comments': self.msg_comment(msg),
            'when_timestamp': self.msg_timestamp(msg),
            'revision': self.msg_revision(msg),
            'properties': self.msg_properties(msg),
        }

    def handleMessage(self, msg):
        d = defer.succeed(None)

        @d.addCallback
        def add_change(_):
            if msg is None:
                return
            return self.master.data.updates.addChange(**self.msg_to_change(msg))

        return d


class SQSJsonSource(SQSSource):
    """
    Behaves just like SQSSource, but where each message sent to the queue is
    a JSON object (i.e. a "dict" in python terminology). This change source
    will deserialize the object and use it as properties in the change.

    The sqs_body property will not be available.
    """
    # maybe we should make it possible to still have the sqs_body prop?
    # perhaps support for valiation using json schemas?
    def msg_properties(self, msg):
        return json.loads(msg)
