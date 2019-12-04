# Copyright 2019- Olof Johansson
# Buildbot mocking infrastructure copyright extracted from buildbot codebase:
#    -2019 Buildbot Team Members
#    Portions copyright 2015-2016 ClusterHQ Inc.

import time
from hashlib import md5
from zope.interface import implementer
from twisted.internet import defer, threads
from twisted.internet.interfaces import IReactorThreads, IReactorCore
from twisted.internet.task import Clock
from twisted.python import threadpool
from twisted.python.failure import Failure
from twisted.trial import unittest
from buildbot.util.eventual import _setReactor

import buildbot_aws_sqs


class NonThreadPool:
    """
    A stand-in for ``twisted.python.threadpool.ThreadPool`` so that the
    majority of the test suite does not need to use multithreading.

    This implementation takes the function call which is meant to run in a
    thread pool and runs it synchronously in the calling thread.

    :ivar int calls: The number of calls which have been dispatched to this
        object.
    """
    calls = 0

    def __init__(self, **kwargs):
        pass

    def callInThreadWithCallback(self, onResult, func, *args, **kw):
        self.calls += 1
        try:
            result = func(*args, **kw)
        except:  # noqa pylint: disable=bare-except
            # We catch *everything* here, since normally this code would be
            # running in a thread, where there is nothing that will catch
            # error.
            onResult(False, Failure())
        else:
            onResult(True, result)

    def start(self):
        pass

    def stop(self):
        pass

@implementer(IReactorCore)
@implementer(IReactorThreads)
class TestReactor(Clock):

    def __init__(self):
        super().__init__()
        self._triggers = {}

        # whether there are calls that should run right now
        self._pendingCurrentCalls = False
        self.stop_called = False

    def callFromThread(self, f, *args, **kwargs):
        f(*args, **kwargs)

    def getThreadPool(self):
        return NonThreadPool()

    def addSystemEventTrigger(self, phase, eventType, f, *args, **kw):
        event = self._triggers.setdefault(eventType, _ThreePhaseEvent())
        return eventType, event.addTrigger(phase, f, *args, **kw)

    def removeSystemEventTrigger(self, triggerID):
        eventType, handle = triggerID
        event = self._triggers.setdefault(eventType, _ThreePhaseEvent())
        event.removeTrigger(handle)

    def fireSystemEvent(self, eventType):
        event = self._triggers.get(eventType)
        if event is not None:
            event.fireEvent()

    def callWhenRunning(self, f, *args, **kwargs):
        f(*args, **kwargs)

    def _executeCurrentDelayedCalls(self):
        while self.getDelayedCalls():
            first = sorted(self.getDelayedCalls(),
                           key=lambda a: a.getTime())[0]
            if first.getTime() > self.seconds():
                break
            self.advance(0)

        self._pendingCurrentCalls = False

    @defer.inlineCallbacks
    def _catchPrintExceptions(self, what, *a, **kw):
        try:
            r = what(*a, **kw)
            if isinstance(r, defer.Deferred):
                yield r
        except Exception as e:
            log.msg('Unhandled exception from deferred when doing '
                    'TestReactor.advance()', e)
            raise

    def callLater(self, when, what, *a, **kw):
        # Buildbot often uses callLater(0, ...) to defer execution of certain
        # code to the next iteration of the reactor. This means that often
        # there are pending callbacks registered to the reactor that might
        # block other code from proceeding unless the test reactor has an
        # iteration. To avoid deadlocks in tests we give the real reactor a
        # chance to advance the test reactor whenever we detect that there
        # are callbacks that should run in the next iteration of the test
        # reactor.
        #
        # Additionally, we wrap all calls with a function that prints any
        # unhandled exceptions
        if when <= 0 and not self._pendingCurrentCalls:
            reactor.callLater(0, self._executeCurrentDelayedCalls)

        return super().callLater(when, self._catchPrintExceptions,
                                 what, *a, **kw)

    def stop(self):
        # first fire pending calls until the current time. Note that the real
        # reactor only advances until the current time in the case of shutdown.
        self.advance(0)

        # then, fire the shutdown event
        self.fireSystemEvent('shutdown')

        self.stop_called = True


class TestReactorMixin:

    """
    Mix this in to get TestReactor as self.reactor which is correctly cleaned up
    at the end
    """
    def setUpTestReactor(self):
        self.patch(threadpool, 'ThreadPool', NonThreadPool)
        self.reactor = TestReactor()
        _setReactor(self.reactor)

        def deferToThread(f, *args, **kwargs):
            return threads.deferToThreadPool(self.reactor, self.reactor.getThreadPool(),
                                             f, *args, **kwargs)
        self.patch(threads, 'deferToThread', deferToThread)

        # During shutdown sequence we must first stop the reactor and only then
        # set unset the reactor used for eventually() because any callbacks
        # that are run during reactor.stop() may use eventually() themselves.
        self.addCleanup(_setReactor, None)
        self.addCleanup(self.reactor.stop)


class DummySQS:
    def __init__(self, **kwargs):
        self.kwargs = kwargs
        self.queue = []

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

    def receive_message(self, **kwargs):
        if not self.queue:
            return {}
        m = self.queue.pop(0)
        return {
            'Messages': [m],
        }

class DummyBoto:
    def client(service, **kwargs):
        assert service == 'sqs'
        return DummySQS(**kwargs)

SQSSource = buildbot_aws_sqs.SQSSource
buildbot_aws_sqs.boto3 = DummyBoto

class TestSQSSource(TestReactorMixin, unittest.TestCase):
    def setUp(self):
        self.sqs_uri = 'http://sqs.example.com/queue'
        self.setUpTestReactor()

    def setup_mock_source(self):
        SQSSource(uri=self.sqs_uri)

    def test_attr_poll_uri(self):
        src = SQSSource(uri=self.sqs_uri)
        self.assertEqual(src.uri, self.sqs_uri)

    def test_attr_poll_interval_default(self):
        src = SQSSource(uri=self.sqs_uri)
        self.assertEqual(src.pollinterval, 60)

    def test_attr_poll_interval_nondefault(self):
        src = SQSSource(uri=self.sqs_uri, pollinterval=3600)
        self.assertEqual(src.pollinterval, 3600)

    def test_attr_aws_region_default(self):
        src = SQSSource(uri=self.sqs_uri)
        self.assertEqual(src.aws_region, 'eu-central-1')

    def test_attr_aws_region_nondefault(self):
        region = 'kuiper-central-1'
        src = SQSSource(uri=self.sqs_uri, aws_region=region)
        self.assertEqual(src.aws_region, region)

    def poll_message(self, src):
        return src.sqs_poll()

    def test_poll_empty(self):
        src = SQSSource(uri=self.sqs_uri)
        resp = src.sqs_poll()
        self.assertEqual(resp.result, None)

    def test_poll_nonempty(self):
        src = SQSSource(uri=self.sqs_uri)
        msg = '{"foo": "bar"}'
        src.sqs.mock_put_msg(msgid='aaaa', msg=msg)
        resp = src.sqs_poll()
        self.assertEqual(resp.result['Body'], msg)

    #def test_describe(self):
    #    src = SQSSource(queue_url=self.sqs_uri)
    #
    #def test_foo(self):
    #    pass
