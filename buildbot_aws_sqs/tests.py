import time
from hashlib import md5
from twisted.internet import defer
from twisted.python.failure import Failure
from twisted.trial import unittest
from unittest.mock import Mock, patch

import botocore.exceptions

import buildbot_aws_sqs
from buildbot_aws_sqs.test_support_gpl import TestReactorMixin


class DummySQS:
    def __init__(self, **kwargs):
        self.kwargs = kwargs
        self.queue = []
        self.delete_message = Mock()

    def mock_put_msg(self, msgid, msg, timestamp=None):
        self.queue.append({
            'MessageId': msgid,
            'Attributes': {
                'SentTimestamp': timestamp or int(time.time() * 1000),
            },
            'ReceiptHandle': 'recipethandle',
            'MD5OfBody': md5(bytes(msg, 'utf-8')).hexdigest(),
            'Body': msg,
        })

    def mock_put_failure(self, exc):
        self.queue.append(exc)

    def receive_message(self, **kwargs):
        if not self.queue:
            return {}
        m = self.queue.pop(0)
        if isinstance(m, Exception):
            raise m
        return {
            'Messages': [m],
        }

class DummyBoto:
    def client(service, **kwargs):
        assert service == 'sqs'
        return DummySQS(**kwargs)

class DummyPool:
    def do(self, cb):
        return defer.succeed(cb(Mock()))

class DummyDB:
    def __init__(self):
        self.pool = DummyPool()

class DummyParent:
    master = Mock()
    master.db = DummyDB()

SQSSource = buildbot_aws_sqs.SQSSource
buildbot_aws_sqs.boto3 = DummyBoto

class TestSQSSource(TestReactorMixin, unittest.TestCase):
    def setUp(self):
        self.sqs_uri = 'http://sqs.example.com/queue'
        self.setUpTestReactor()

    def client_error(self, msg,
                     code='InternalError',
                     operation_name='ReceiveMessage',
                     http_code=500):
        return botocore.exceptions.ClientError(
            error_response={
                'ResponseMetadata': {
                    'HTTPStatusCode': http_code,
                },
                'Error': {'Code': code, 'Message': msg}
            },
            operation_name=operation_name,
        )

    def test_attr_poll_uri(self):
        src = SQSSource('test', uri=self.sqs_uri)
        self.assertEqual(src.uri, self.sqs_uri)

    def test_attr_name(self):
        src = SQSSource('test', uri=self.sqs_uri)
        self.assertEqual(src.name, 'test')

    def test_attr_poll_interval_default(self):
        src = SQSSource('test', uri=self.sqs_uri)
        self.assertEqual(src.pollinterval, 60)

    def test_attr_poll_interval_nondefault(self):
        src = SQSSource('test', uri=self.sqs_uri, pollinterval=3600)
        self.assertEqual(src.pollinterval, 3600)

    def test_attr_aws_region_default(self):
        src = SQSSource('test', uri=self.sqs_uri)
        self.assertEqual(src.aws_region, 'eu-central-1')

    def test_attr_aws_region_nondefault(self):
        region = 'kuiper-central-1'
        src = SQSSource('test', uri=self.sqs_uri, aws_region=region)
        self.assertEqual(src.aws_region, region)

    def poll_message(self, src):
        return src.sqs_poll()

    def test_poll_empty(self):
        src = SQSSource('test', uri=self.sqs_uri)
        resp = src.sqs_poll()
        self.assertEqual(resp.result, None)

    def test_poll_nonempty(self):
        src = SQSSource('test', uri=self.sqs_uri)
        msg = '{"foo": "bar"}'
        src.sqs.mock_put_msg(msgid='aaaa', msg=msg)
        resp = src.sqs_poll()
        self.assertEqual(resp.result['Body'], msg)

    def test_fail_credential_retrieve(self):
        src = SQSSource('test', uri=self.sqs_uri)
        src.sqs.mock_put_failure(botocore.exceptions.CredentialRetrievalError(
            provider='FailingMockProvider',
            error_msg='this error is part of the tests',
        ))
        src.log = Mock()
        resp = src.sqs_poll()
        self.assertEqual(resp.result, None)
        src.log.error.assert_called_once()

    def test_fail_client_error(self):
        src = SQSSource('test', uri=self.sqs_uri)
        src.sqs.mock_put_failure(self.client_error('error testing'))
        src.log = Mock()
        resp = src.sqs_poll()
        self.assertEqual(resp.result, None)
        src.log.error.assert_called_once()

    def test_fail_client_error_bad_format(self):
        src = SQSSource('test', uri=self.sqs_uri)
        src.sqs.mock_put_failure(
            botocore.exceptions.ClientError(
                error_response={},
                operation_name="ReceiveMessage",
            )
        )
        src.log = Mock()
        resp = src.sqs_poll()
        self.assertEqual(resp.result, None)
        src.log.error.assert_called_once()

    def test_poll_dupe(self):
        src = SQSSource('test', uri=self.sqs_uri)
        src.parent = DummyParent()
        msg = '{"foo": "bar"}'

        # first message
        # should trigger handle_message, delete_message
        src.sqs.mock_put_msg(msgid='aaaa', msg=msg)
        src.change_exists = lambda self, rev: False

        resp1 = src.poll()
        self.assertEqual(src.sqs.delete_message.call_count, 1)
        self.assertEqual(src.master.data.updates.addChange.call_count, 1)

        # second message (same message again)
        # should trigger delete_message but not handle_message
        src.sqs.mock_put_msg(msgid='aaaa', msg=msg)
        src.change_exists = lambda self, rev: True
        resp2 = src.poll()
        self.assertEqual(src.sqs.delete_message.call_count, 2)
        self.assertEqual(src.master.data.updates.addChange.call_count, 1)

    #def test_describe(self):
    #    src = SQSSource('test', queue_url=self.sqs_uri)
    #
    #def test_foo(self):
    #    pass
