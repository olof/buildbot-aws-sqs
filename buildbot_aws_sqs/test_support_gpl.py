# This file has been extracted from Buildbot. Buildbot is free software: you can
# redistribute it and/or modify it under the terms of the GNU General Public
# License as published by the Free Software Foundation, version 2.
#
# This program is distributed in the hope that it will be useful, but WITHOUT
# ANY WARRANTY; without even the implied warranty of MERCHANTABILITY or FITNESS
# FOR A PARTICULAR PURPOSE.  See the GNU General Public License for more
# details.
#
# You should have received a copy of the GNU General Public License along with
# this program; if not, write to the Free Software Foundation, Inc., 51
# Franklin Street, Fifth Floor, Boston, MA 02110-1301 USA.
#
# Copyright Buildbot Team Members
#
# (Please find GPLv2 text in LICENSE.tests in the top directory
# of buildbot-aws-sqs.)

from twisted.python import threadpool
from twisted.internet import threads
from buildbot_aws_sqs.test_support import NonThreadPool, TestReactor
from buildbot.util.eventual import _setReactor

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
