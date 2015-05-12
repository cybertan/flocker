# Copyright Hybrid Logic Ltd.  See LICENSE file for details.

"""
Tests for :module:`flocker.node.script`.
"""
import netifaces
import yaml

from jsonschema.exceptions import ValidationError

from zope.interface.verify import verifyObject

from twisted.internet.defer import Deferred
from twisted.python.filepath import FilePath
from twisted.trial.unittest import SynchronousTestCase
from twisted.application.service import Service

from ...common.script import ICommandLineScript

from ..script import (
    AgentScript, ContainerAgentOptions,
    AgentServiceFactory, DatasetAgentOptions, validate_configuration)
from .._loop import AgentLoopService
# TODO Make tests which use this
# from .._deploy import P2PManifestationDeployer
# TODO test for configurationerror on missing config file
# from ...control import ConfigurationError
from ...testtools import MemoryCoreReactor


# TODO make these generic tests for each backend
# class ZFSAgentScriptTests(SynchronousTestCase):
#     """
#     Tests for ``ZFSAgentScript``.
#     """
#     def setUp(self):
#         scratch_directory = FilePath(self.mktemp())
#         scratch_directory.makedirs()
#         self.config = scratch_directory.child('dataset-config.yml')
#         self.config.setContent(yaml.safe_dump({
#             u"control-service": {
#                 u"hostname": u"10.0.0.1",
#                 u"port": 1234,
#             },
#             u"dataset": {
#                 u"backend": u"zfs",
#                 u"zfs-pool": u"custom-pool",
#             },
#             u"version": 1,
#         }))
#
#     def test_main_starts_service(self):
#         """
#         ``ZFSAgentScript.main`` starts the given service.
#         """
#         service = Service()
#         options = ZFSAgentOptions()
#         options.parseOptions([b"--agent-config", self.config.path])
#         ZFSAgentScript().main(MemoryCoreReactor(), options, service)
#         self.assertTrue(service.running)
#
#     def test_no_immediate_stop(self):
#         """
#         The ``Deferred`` returned from ``ZFSAgentScript`` is not fired.
#         """
#         script = ZFSAgentScript()
#         options = ZFSAgentOptions()
#         options.parseOptions([b"--agent-config", self.config.path])
#         self.assertNoResult(script.main(MemoryCoreReactor(), options,
#                                         Service()))
#
#     def test_starts_convergence_loop(self):
#         """
#         ``ZFSAgentScript.main`` starts a convergence loop service.
#         """
#         service = Service()
#         options = ZFSAgentOptions()
#         options.parseOptions([b"--agent-config", self.config.path])
#         test_reactor = MemoryCoreReactor()
#         ZFSAgentScript().main(test_reactor, options, service)
#         parent_service = service.parent
#         # P2PManifestationDeployer is difficult to compare automatically,
#         # so do so manually:
#         deployer = parent_service.deployer
#         parent_service.deployer = None
#         self.assertEqual((parent_service, deployer.__class__,
#                           deployer.volume_service,
#                           parent_service.running),
#                          (AgentLoopService(reactor=test_reactor,
#                                            deployer=None,
#                                            host=u"10.0.0.1",
#                                            port=1234),
#                           P2PManifestationDeployer, service, True))


def get_all_ips():
    """
    Find all IPs for this machine.

    :return: ``list`` of IP addresses (``bytes``).
    """
    ips = []
    interfaces = netifaces.interfaces()
    for interface in interfaces:
        addresses = netifaces.ifaddresses(interface)
        ipv4 = addresses.get(netifaces.AF_INET)
        if not ipv4:
            continue
        for address in ipv4:
            ips.append(address['addr'])
    return ips


class AgentServiceFactoryTests(SynchronousTestCase):
    """
    Tests for ``AgentServiceFactory``.
    """
    def setUp(self):
        scratch_directory = FilePath(self.mktemp())
        scratch_directory.makedirs()
        self.config = scratch_directory.child('dataset-config.yml')
        self.config.setContent(
            yaml.safe_dump({
                u"control-service": {
                    u"hostname": u"10.0.0.2",
                    u"port": 1234,
                },
                u"dataset": {
                    u"backend": u"zfs",
                    u"zfs-pool": u"custom-pool",
                },
                u"version": 1,
            }))

    def test_get_service(self):
        """
        ``AgentServiceFactory.get_service`` creates ``AgentLoopService``
        configured with the destination given in the config file given by the
        options.
        """
        deployer = object()

        def factory(**kw):
            expected = {
                "dataset_configuration", "reactor", "node_uuid", "hostname"}
            self.assertEqual(set(kw.keys()), expected)
            return deployer

        reactor = MemoryCoreReactor()
        options = DatasetAgentOptions()
        options.parseOptions([b"--agent-config", self.config.path])
        service_factory = AgentServiceFactory(
            deployer_factory=factory
        )
        self.assertEqual(
            AgentLoopService(
                reactor=reactor,
                deployer=deployer,
                host=b"10.0.0.2",
                port=1234,
            ),
            service_factory.get_service(reactor, options)
        )

    def test_deployer_factory_called_with_ip(self):
        """
        ``AgentServiceFactory.main`` calls its ``deployer_factory`` with one
        of the node's IPs.
        """
        spied = []

        def deployer_factory(dataset_configuration, reactor, node_uuid,
                             hostname):
            spied.append(hostname)
            return object()

        reactor = MemoryCoreReactor()
        options = DatasetAgentOptions()
        options.parseOptions([b"--agent-config", self.config.path])
        agent = AgentServiceFactory(deployer_factory=deployer_factory)
        agent.get_service(reactor, options)
        self.assertIn(spied[0], get_all_ips())


class AgentScriptTests(SynchronousTestCase):
    """
    Tests for ``AgentScript``.
    """
    def setUp(self):
        self.reactor = MemoryCoreReactor()
        self.options = DatasetAgentOptions()

    def test_interface(self):
        """
        ``AgentScript`` instances provide ``ICommandLineScript``.
        """
        self.assertTrue(
            verifyObject(
                ICommandLineScript,
                AgentScript(
                    service_factory=lambda reactor, options: Service()
                )
            )
        )

    def test_service_factory_called_with_main_arguments(self):
        """
        ``AgentScript`` calls the ``service_factory`` with the reactor
        and options passed to ``AgentScript.main``.
        """
        args = []
        service = Service()

        def service_factory(reactor, options):
            args.append((reactor, options))
            return service

        agent = AgentScript(service_factory=service_factory)
        agent.main(self.reactor, self.options)
        self.assertEqual([(self.reactor, self.options)], args)

    def test_main_starts_service(self):
        """
        ```AgentScript.main`` starts the service created by its
        ``service_factory`` .
        """
        service = Service()
        agent = AgentScript(
            service_factory=lambda reactor, options: service
        )
        agent.main(self.reactor, self.options)
        self.assertTrue(service.running)

    def test_main_stops_service(self):
        """
        When the reactor passed to ``AgentScript.main`` shuts down, the
        service created by the ``service_factory`` is stopped.
        """
        service = Service()
        agent = AgentScript(
            service_factory=lambda reactor, options: service
        )
        agent.main(self.reactor, self.options)
        self.reactor.fireSystemEvent("shutdown")
        self.assertFalse(service.running)

    def test_main_deferred_fires_after_service_stop(self):
        """
        The ``Deferred`` returned by ``AgentScript.main`` doesn't fire
        until after the ``Deferred`` returned by the ``stopService`` method of
        the service created by ``service_factory``.
        """
        shutdown_deferred = Deferred()

        class SlowShutdown(Service):
            def stopService(self):
                return shutdown_deferred

        service = SlowShutdown()
        agent = AgentScript(
            service_factory=lambda reactor, options: service
        )
        stop_deferred = agent.main(self.reactor, self.options)
        self.reactor.fireSystemEvent("shutdown")
        self.assertNoResult(stop_deferred)
        shutdown_deferred.callback(None)
        self.assertIs(None, self.successResultOf(stop_deferred))


def make_amp_agent_options_tests(options_type):
    """
    Create a test case which contains the tests that should apply to any and
    all convergence agents (dataset or container).

    :param options_type: An ``Options`` subclass  to be tested.

    :return: A ``SynchronousTestCase`` subclass defining tests for that options
        type.
    """

    class Tests(SynchronousTestCase):
        def setUp(self):
            self.options = options_type()
            self.scratch_directory = FilePath(self.mktemp())
            self.scratch_directory.makedirs()
            self.sample_content = yaml.safe_dump({
                u"control-service": {
                    u"hostname": u"10.0.0.1",
                    u"port": 4524,
                },
                u"version": 1,
            })
            self.config = self.scratch_directory.child('dataset-config.yml')
            self.config.setContent(self.sample_content)

        def test_default_config_file(self):
            """
            The default config file is a FilePath with path
            ``/etc/flocker/agent.yml``.
            """
            self.options.parseOptions([])
            self.assertEqual(
                self.options["agent-config"],
                FilePath("/etc/flocker/agent.yml"))

        def test_custom_config_file(self):
            """
            The ``--config-file`` command-line option allows configuring
            the config file.
            """
            self.options.parseOptions(
                [b"--agent-config", b"/etc/foo.yml"])
            self.assertEqual(
                self.options["agent-config"],
                FilePath("/etc/foo.yml"))

    return Tests


class AgentConfigFromFileTests(SynchronousTestCase):
    """
    Tests for :func:`agent_config_from_file`.
    """

    def setUp(self):
        self.scratch_directory = FilePath(self.mktemp())
        self.scratch_directory.makedirs()
        self.config_file = self.scratch_directory.child('config.yml')
        # This is a sample working configuration which tests can modify.
        self.configuration = {
            u"control-service": {
                u"hostname": u"10.0.0.1",
                u"port": 1234,
            },
            u"dataset": {
                u"backend": u"zfs",
                u"zfs-pool": u"custom-pool",
            },
            "version": 1,
        }

    def assertErrorForConfig(self):
        """
        Assert that given a particular configuration,
        :func:`agent_config_from_file` will fail with an expected exception
        and message.

        :param Exception exception: The exception type which
            :func:`agent_config_from_file` should fail with.
        :param dict configuration: The contents of the agent configuration
            file. If ``None`` then the file will not exist.
        :param bytes message: The expected exception message.
        """
        self.assertRaises(
            ValidationError,
            validate_configuration, self.configuration)

    def test_configuration_returned(self):
        """
        A dictionary specifying the desired agent configuration is returned
        when a valid configuration file is given.
        """
        # TODO change docstring
        # TODO test with other options, use build_schema test
        # like loopback option
        # TODO separate out checking for existance and validation

        # Nothing is raised
        validate_configuration(self.configuration)

    def test_error_on_invalid_config(self):
        """
        A ``ConfigurationError`` is raised if the config file is not formatted
        as a dictionary.
        """
        self.configuration = "INVALID"
        self.assertErrorForConfig()

    def test_error_on_invalid_hostname(self):
        """
        A ``ConfigurationError`` is raised if the given control service
        hostname is not a valid hostname.
        """
        self.configuration['control-service']['hostname'] = u"-1"

        self.assertErrorForConfig()

    def test_error_on_missing_control_service(self):
        """
        A ``ConfigurationError`` is raised if the config file does not
        contain a ``u"control-service"`` key.
        """
        self.configuration.pop('control-service')

        self.assertErrorForConfig()

    def test_error_on_missing_hostname(self):
        """
        A ``ConfigurationError`` is raised if the config file does not
        contain a hostname in the ``u"control-service"`` key.
        """
        self.configuration['control-service'].pop('hostname')
        self.assertErrorForConfig()

    def test_error_on_missing_version(self):
        """
        A ``ConfigurationError`` is raised if the config file does not contain
        a ``u"version"`` key.
        """
        self.configuration.pop('version')

        self.assertErrorForConfig()

    def test_error_on_high_version(self):
        """
        A ``ConfigurationError`` is raised if the version specified is greater
        than 1.
        """
        self.configuration['version'] = 2

        self.assertErrorForConfig()

    def test_error_on_low_version(self):
        """
        A ``ConfigurationError`` is raised if the version specified is lower
        than 1.
        """
        self.configuration['version'] = 0.5

        self.assertErrorForConfig()

    def test_error_on_invalid_port(self):
        """
        The control service agent's port must be an integer.
        """
        self.configuration['control-service']['port'] = 1.1

        self.assertErrorForConfig()

    def test_error_on_missing_dataset(self):
        """
        A ``ConfigurationError`` is raised if the config file does not contain
        a ``u"dataset"`` key.
        """
        self.configuration.pop('dataset')

        self.assertErrorForConfig()

    def test_error_on_missing_dataset_backend(self):
        """
        The dataset key must contain a backend type.
        """
        self.configuration['dataset'] = {}
        self.assertErrorForConfig()

    def test_error_on_invalid_dataset_type(self):
        """
        The dataset key must contain a valid dataset type.
        """
        self.configuration['dataset'] = {"backend": "invalid"}
        self.assertErrorForConfig()


class DatasetAgentOptionsTests(
        make_amp_agent_options_tests(DatasetAgentOptions)
):
    """
    Tests for ``DatasetAgentOptions``.
    """


class ContainerAgentOptionsTests(
        make_amp_agent_options_tests(ContainerAgentOptions)
):
    """
    Tests for ``ContainerAgentOptions``.
    """
