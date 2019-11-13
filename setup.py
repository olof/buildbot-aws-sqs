from setuptools import setup, find_packages

setup(
    name='buildbot_aws_sqs',
    version='0.1.0',
    description='buildbot aws sqs support',
    author='olof johansson',
    author_email='olof@ethup.se',
    packages=find_packages(),
    install_requires=[
        'buildbot>=2.5.0',
        'twisted',
        'boto3',
    ],
    entry_points = {
        'buildbot.changes': [
            'PluginName = buildbot_aws_sqs:SQSSource'
        ]
    },
)
