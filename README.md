# buildbot_aws_sqs

**Currently unpublished on PyPI. Consider this a thought
experiment until it is. If you use it in your production critical
environments and it works, let me know and I'll consider removing
this disclaimer! My API design may very well be totally broken,
so no stability guarantees. Also, I've hidden a cryptominer in
the code somewhere! (Or did I?)**

**The master branch of this repository may be rebased until this
notice is removed. Let me know if this would be a problem for
you.**

This package adds support for AWS SQS based changesources to
buildbot, in the form of the SQSSource class. For each message
sent to a subscribed queue, a change is generated. By default,
the change contains an `sqs_body` property, containing the
message body as a string. Subscribe to these changes with a
scheduler to trigger builds by pushing messages to SQS.

```python
# some idea about what master.cfg would look like:
...

from buildbot_aws_sqs import SQSSource

BuilderMasterConfig['change_source'] = [
    SQSSource(
        uri='https://eu-central-1.queue.amazonaws.com/999999999999/queue',
        codebase='models',
    ),
]

BuilderMasterConfig['schedulers'] = [
    schedulers.AnyBranchScheduler(
        name='incoming_models',
        codebases=['models'],
        builderNames=['build_model_assets'],
    ),
]

BuilderMasterConfig['builders'] = [
    util.BuilderConfig(
        name='build_model_assets',
	...
    )
]

...
```

Optionally, subclass the SQSSource class to add queue specific
handling, e.g. message deserialisation and unpacking.

```python
class MyQueueSource(SQSSource):
    def msg_properties(self, msg):
        m = json.loads(msg)

	# Let's say your message contains an "action" param
        return {
            'sqs_body': msg,
	    'action': m['action'],
        }
```
