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

There's also a SQSJsonSource which assumes that all messages are
JSON objects, and will set the change properties to that of the
deserialized object; a message like `{"foo": "bar"}` would thus
generate a change with a "foo" property that you can interpolate
in triggered builds.

```python
from buildbot_aws_sqs import SQSSource

BuilderMasterConfig['change_source'] = [
    SQSJsonSource(
        uri='https://eu-central-1.queue.amazonaws.com/999999999999/queue',
        codebase='models',
    ),
]
```

Or, you can subclass the SQSSource (or SQSJsonSource) class to
add queue specific handling, e.g. message deserialisation and
unpacking.

```python
class MyCustomSource(SQSSource):
    def msg_properties(self, msg):
        # Messages consists of a single line "action <some action>"
        m = re.match(r'^action (.*)', msg['Body'])
        action = m.group(1) or 'default'
        return {
            'action': m.group(1) or 'default',
        }
```
