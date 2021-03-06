"""This contains all Bcfg2 Tool modules"""

import os
import sys
import stat
import select
from subprocess import Popen, PIPE
import Bcfg2.Client.XML
from Bcfg2.Compat import input, walk_packages  # pylint: disable=W0622

__all__ = [m[1] for m in walk_packages(path=__path__)]

# pylint: disable=C0103
#: All available tools
drivers = [item for item in __all__ if item not in ['rpmtools']]

#: The default set of tools that will be used if "drivers" is not set
#: in bcfg2.conf
default = drivers[:]
# pylint: enable=C0103


class ToolInstantiationError(Exception):
    """ This error is raised if the toolset cannot be instantiated. """
    pass


class Executor:
    """ This class runs shell commands. """

    def __init__(self, logger):
        """
        :param logger: The logger to use to produce debug logging
        :type logger: logging.Logger
        """
        self.logger = logger

    def run(self, command):
        """ Run a command inside a shell.

        :param command: The command to run, given as a list as to
                        :class:`subprocess.Popen`.  Since the command
                        will be run within a shell it is particularly
                        important to pass it as a list.
        :type command: list
        :returns: tuple of return value (integer) and output (list of
                  lines)
        """
        self.logger.debug("Running: %s" % command)
        proc = Popen(command, shell=True, bufsize=16384,
                     stdin=PIPE, stdout=PIPE, close_fds=True)
        output = proc.communicate()[0].splitlines()
        for line in output:
            self.logger.debug('< %s' % line)
        return (proc.wait(), output)


class ClassName(object):
    """ This very simple descriptor class exists only to get the name
    of the owner class.  This is used because, for historical reasons,
    we expect every tool to have a ``name`` attribute that is in
    almost all cases the same as the ``__class__.__name__`` attribute
    of the plugin object.  This makes that more dynamic so that each
    plugin isn't repeating its own name."""

    def __get__(self, inst, owner):
        return owner.__name__


class Tool(object):
    """ The base tool class.  All tools subclass this.

    .. private-include: _entry_is_complete
    .. autoattribute:: Bcfg2.Client.Tools.Tool.__execs__
    .. autoattribute:: Bcfg2.Client.Tools.Tool.__handles__
    .. autoattribute:: Bcfg2.Client.Tools.Tool.__req__
    .. autoattribute:: Bcfg2.Client.Tools.Tool.__important__
    """

    #: The name of the tool.  By default this uses
    #: :class:`Bcfg2.Client.Tools.ClassName` to ensure that it is the
    #: same as the name of the class.
    name = ClassName()

    #: Full paths to all executables the tool uses.  When the tool is
    #: instantiated it will check to ensure that all of these files
    #: exist and are executable.
    __execs__ = []

    #: A list of 2-tuples of entries handled by this tool.  Each
    #: 2-tuple should contain ``(<tag>, <type>)``, where ``<type>`` is
    #: the ``type`` attribute of the entry.  If this tool handles
    #: entries with no ``type`` attribute, specify None.
    __handles__ = []

    #: A dict that describes the required attributes for entries
    #: handled by this tool.  The keys are the names of tags.  The
    #: values may either be lists of attribute names (if the same
    #: attributes are required by all tags of that name), or dicts
    #: whose keys are the ``type`` attribute and whose values are
    #: lists of attributes required by tags with that ``type``
    #: attribute.  In that case, the ``type`` attribute will also be
    #: required.
    __req__ = {}

    #: A list of entry names that will be treated as important and
    #: installed before other entries.
    __important__ = []

    #: This tool is deprecated, and a warning will be produced if it
    #: is used.
    deprecated = False

    #: This tool is experimental, and a warning will be produced if it
    #: is used.
    experimental = False

    #: List of other tools (by name) that this tool conflicts with.
    #: If any of the listed tools are loaded, they will be removed at
    #: runtime with a warning.
    conflicts = []

    def __init__(self, logger, setup, config):
        """
        :param logger: Logger that will be used for logging by this tool
        :type logger: logging.Logger
        :param setup: The option set Bcfg2 was invoked with
        :type setup: Bcfg2.Options.OptionParser
        :param config: The XML configuration for this client
        :type config: lxml.etree._Element
        :raises: :exc:`Bcfg2.Client.Tools.ToolInstantiationError`
        """
        #: A :class:`Bcfg2.Options.OptionParser` object describing the
        #: option set Bcfg2 was invoked with
        self.setup = setup

        #: A :class:`logging.Logger` object that will be used by this
        #: tool for logging
        self.logger = logger

        #: The XML configuration for this client
        self.config = config

        #: An :class:`Bcfg2.Client.Tools.Executor` object for
        #: running external commands.
        self.cmd = Executor(logger)

        #: A list of entries that have been modified by this tool
        self.modified = []

        #: A list of extra entries that are not listed in the
        #: configuration
        self.extra = []

        #: A list of all entries handled by this tool
        self.handled = []

        for struct in config:
            for entry in struct:
                if (entry.tag == 'Path' and
                    entry.get('important', 'false').lower() == 'true'):
                    self.__important__.append(entry.get('name'))
                if self.handlesEntry(entry):
                    self.handled.append(entry)
        for filename in self.__execs__:
            try:
                mode = stat.S_IMODE(os.stat(filename)[stat.ST_MODE])
                if mode & stat.S_IEXEC != stat.S_IEXEC:
                    raise ToolInstantiationError("%s: %s not executable" %
                                                 (self.name, filename))
            except OSError:
                raise ToolInstantiationError(sys.exc_info()[1])
            except:
                raise ToolInstantiationError("%s: Failed to stat %s" %
                                             (self.name, filename),
                                             exc_info=1)

    def BundleUpdated(self, bundle, states):  # pylint: disable=W0613
        """ Callback that is invoked when a bundle has been updated.

        :param bundle: The bundle that has been updated
        :type bundle: lxml.etree._Element
        :param states: The :attr:`Bcfg2.Client.Frame.Frame.states` dict
        :type states: dict
        :returns: None """
        return

    def BundleNotUpdated(self, bundle, states):  # pylint: disable=W0613
        """ Callback that is invoked when a bundle has been updated.

        :param bundle: The bundle that has been updated
        :type bundle: lxml.etree._Element
        :param states: The :attr:`Bcfg2.Client.Frame.Frame.states` dict
        :type states: dict
        :returns: None """
        return

    def Inventory(self, states, structures=None):
        """ Take an inventory of the system as it exists.  This
        involves two steps:

        * Call the appropriate entry-specific Verify method for each
          entry this tool verifies;
        * Call :func:`Bcfg2.Client.Tools.Tool.FindExtra` to populate
          :attr:`Bcfg2.Client.Tools.Tool.extra` with extra entries.

        This implementation of
        :func:`Bcfg2.Client.Tools.Tool.Inventory` calls a
        ``Verify<tag>`` method to verify each entry, where ``<tag>``
        is the entry tag.  E.g., a Path entry would be verified by
        calling :func:`VerifyPath`.

        :param states: The :attr:`Bcfg2.Client.Frame.Frame.states` dict
        :type states: dict
        :param structures: The list of structures (i.e., bundles) to
                           get entries from.  If this is not given,
                           all children of
                           :attr:`Bcfg2.Client.Tools.Tool.config` will
                           be used.
        :type structures: list of lxml.etree._Element
        :returns: None """
        if not structures:
            structures = self.config.getchildren()
        mods = self.buildModlist()
        for struct in structures:
            for entry in struct.getchildren():
                if self.canVerify(entry):
                    try:
                        func = getattr(self, "Verify%s" % entry.tag)
                        states[entry] = func(entry, mods)
                    except AttributeError:
                        self.logger.error("%s: Cannot verify %s entries" %
                                          (self.name, entry.tag))
                    except:
                        self.logger.error("%s: Unexpected failure verifying %s"
                                          % (self.name,
                                             self.primarykey(entry)),
                                          exc_info=1)
        self.extra = self.FindExtra()

    def Install(self, entries, states):
        """ Install entries.  'Install' in this sense means either
        initially install, or update as necessary to match the
        specification.

        This implementation of :func:`Bcfg2.Client.Tools.Tool.Install`
        calls a ``Install<tag>`` method to install each entry, where
        ``<tag>`` is the entry tag.  E.g., a Path entry would be
        installed by calling :func:`InstallPath`.

        :param entries: The entries to install
        :type entries: list of lxml.etree._Element
        :param states: The :attr:`Bcfg2.Client.Frame.Frame.states` dict
        :type states: dict
        :returns: None """
        for entry in entries:
            try:
                func = getattr(self, "Install%s" % (entry.tag))
                states[entry] = func(entry)
                if states[entry]:
                    self.modified.append(entry)
            except AttributeError:
                self.logger.error("%s: Cannot install %s entries" %
                                  (self.name, entry.tag))
            except:
                self.logger.error("%s: Unexpected failure installing %s" %
                                  (self.name, self.primarykey(entry)),
                                  exc_info=1)

    def Remove(self, entries):
        """ Remove specified extra entries.

        :param entries: The entries to remove
        :type entries: list of lxml.etree._Element
        :returns: None """
        pass

    def getSupportedEntries(self):
        """ Get all entries that are handled by this tool.

        :returns: list of lxml.etree._Element """
        rv = []
        for struct in self.config.getchildren():
            rv.extend([entry for entry in struct.getchildren()
                       if self.handlesEntry(entry)])
        return rv

    def handlesEntry(self, entry):
        """ Return True if the entry is handled by this tool.

        :param entry: Determine if this entry is handled.
        :type entry: lxml.etree._Element
        :returns: bool
        """
        return (entry.tag, entry.get('type')) in self.__handles__

    def buildModlist(self):
        """ Build a list of all Path entries in the configuration.
        (This can be used to determine which paths might be modified
        from their original state, useful for verifying packages)

        :returns: list of lxml.etree._Element """
        rv = []
        for struct in self.config.getchildren():
            rv.extend([entry.get('name') for entry in struct.getchildren()
                       if entry.tag == 'Path'])
        return rv

    def missing_attrs(self, entry):
        """ Return a list of attributes that were expected on an entry
        (from :attr:`Bcfg2.Client.Tools.Tool.__req__`), but not found.

        :param entry: The entry to find missing attributes on
        :type entry: lxml.etree._Element
        :returns: list of strings """
        required = self.__req__[entry.tag]
        if isinstance(required, dict):
            required = ["type"]
            try:
                required.extend(self.__req__[entry.tag][entry.get("type")])
            except KeyError:
                pass

        return [attr for attr in required
                if attr not in entry.attrib or not entry.attrib[attr]]

    def canVerify(self, entry):
        """ Test if entry can be verified by calling
        :func:`Bcfg2.Client.Tools.Tool._entry_is_complete`.

        :param entry: The entry to evaluate
        :type entry: lxml.etree._Element
        :returns: bool - True if the entry can be verified, False
                  otherwise.
        """
        return self._entry_is_complete(entry, action="verify")

    def FindExtra(self):
        """ Return a list of extra entries, i.e., entries that exist
        on the client but are not in the configuration.

        :returns: list of lxml.etree._Element """
        return []

    def primarykey(self, entry):
        """ Return a string that describes the entry uniquely amongst
        all entries in the configuration.

        :param entry: The entry to describe
        :type entry: lxml.etree._Element
        :returns: string """
        return "%s:%s" % (entry.tag, entry.get("name"))

    def canInstall(self, entry):
        """ Test if entry can be installed by calling
        :func:`Bcfg2.Client.Tools.Tool._entry_is_complete`.

        :param entry: The entry to evaluate
        :type entry: lxml.etree._Element
        :returns: bool - True if the entry can be installed, False
                  otherwise.
        """
        return self._entry_is_complete(entry, action="install")

    def _entry_is_complete(self, entry, action=None):
        """ Test if the entry is complete.  This involves three
        things:

        * The entry is handled by this tool (as reported by
          :func:`Bcfg2.Client.Tools.Tool.handlesEntry`;
        * The entry does not report a bind failure;
        * The entry is not missing any attributes (as reported by
          :func:`Bcfg2.Client.Tools.Tool.missing_attrs`).

        :param entry: The entry to evaluate
        :type entry: lxml.etree._Element
        :param action: The action being performed on the entry (e.g.,
                      "install", "verify").  This is used to produce
                      error messages; if not provided, generic error
                      messages will be used.
        :type action: string
        :returns: bool - True if the entry can be verified, False
                  otherwise.
        """
        if not self.handlesEntry(entry):
            return False

        if 'failure' in entry.attrib:
            if action is None:
                msg = "%s: %s reports bind failure"
            else:
                msg = "%%s: Cannot %s entry %%s with bind failure" % action
            self.logger.error(msg % (self.name, self.primarykey(entry)))
            return False

        missing = self.missing_attrs(entry)
        if missing:
            if action is None:
                desc = "%s is" % self.primarykey(entry)
            else:
                desc = "Cannot %s %s due to" % (action, self.primarykey(entry))
            self.logger.error("%s: %s missing required attribute(s): %s" %
                              (self.name, desc, ", ".join(missing)))
            return False
        return True


class PkgTool(Tool):
    """ PkgTool provides a one-pass install with fallback for use with
    packaging systems.  PkgTool makes a number of assumptions that may
    need to be overridden by a subclass.  For instance, it assumes
    that packages are installed by a shell command; that only one
    version of a given package can be installed; etc.  Nonetheless, it
    offers a strong base for writing simple package tools. """

    #: A tuple describing the format of the command to run to install
    #: a single package.  The first element of the tuple is a string
    #: giving the format of the command, with a single '%s' for the
    #: name of the package or packages to be installed.  The second
    #: element is a tuple whose first element is the format of the
    #: name of the package, and whose second element is a list whose
    #: members are the names of attributes that will be used when
    #: formatting the package name format string.
    pkgtool = ('echo %s', ('%s', ['name']))

    #: The ``type`` attribute of Packages handled by this tool.
    pkgtype = 'echo'

    def __init__(self, logger, setup, config):
        Tool.__init__(self, logger, setup, config)

        #: A dict of installed packages; the keys should be package
        #: names and the values should be simple strings giving the
        #: installed version.
        self.installed = {}
        self.RefreshPackages()

    def VerifyPackage(self, entry, modlist):
        """ Verify the given Package entry.

        :param entry: The Package entry to verify
        :type entry: lxml.etree._Element
        :param modlist: A list of all Path entries in the
                        configuration, which may be considered when
                        verifying a package.  For instance, a package
                        should verify successfully if paths in
                        ``modlist`` have been modified outside the
                        package.
        :type modlist: list of strings
        :returns: bool - True if the package verifies, false otherwise.
        """
        raise NotImplementedError

    def Install(self, packages, states):
        """ Run a one-pass install where all required packages are
        installed with a single command, followed by single package
        installs in case of failure.

        :param entries: The entries to install
        :type entries: list of lxml.etree._Element
        :param states: The :attr:`Bcfg2.Client.Frame.Frame.states` dict
        :type states: dict
        :returns: None """
        self.logger.info("Trying single pass package install for pkgtype %s" %
                         self.pkgtype)

        data = [tuple([pkg.get(field) for field in self.pkgtool[1][1]])
                for pkg in packages]
        pkgargs = " ".join([self.pkgtool[1][0] % datum for datum in data])

        self.logger.debug("Installing packages: %s" % pkgargs)
        self.logger.debug("Running command: %s" % (self.pkgtool[0] % pkgargs))

        cmdrc = self.cmd.run(self.pkgtool[0] % pkgargs)[0]
        if cmdrc == 0:
            self.logger.info("Single Pass Succeded")
            # set all package states to true and flush workqueues
            pkgnames = [pkg.get('name') for pkg in packages]
            for entry in list(states.keys()):
                if (entry.tag == 'Package'
                    and entry.get('type') == self.pkgtype
                    and entry.get('name') in pkgnames):
                    self.logger.debug('Setting state to true for pkg %s' %
                                      (entry.get('name')))
                    states[entry] = True
            self.RefreshPackages()
        else:
            self.logger.error("Single Pass Failed")
            # do single pass installs
            self.RefreshPackages()
            for pkg in packages:
                # handle state tracking updates
                if self.VerifyPackage(pkg, []):
                    self.logger.info("Forcing state to true for pkg %s" %
                                     (pkg.get('name')))
                    states[pkg] = True
                else:
                    self.logger.info("Installing pkg %s version %s" %
                                     (pkg.get('name'), pkg.get('version')))
                    cmdrc = self.cmd.run(
                        self.pkgtool[0] %
                        (self.pkgtool[1][0] %
                         tuple([pkg.get(field)
                                for field in self.pkgtool[1][1]])))
                    if cmdrc[0] == 0:
                        states[pkg] = True
                    else:
                        self.logger.error("Failed to install package %s" %
                                          (pkg.get('name')))
            self.RefreshPackages()
        for entry in [ent for ent in packages if states[ent]]:
            self.modified.append(entry)

    def RefreshPackages(self):
        """ Refresh the internal representation of the package
        database (:attr:`Bcfg2.Client.Tools.PkgTool.installed`).

        :returns: None"""
        raise NotImplementedError

    def FindExtra(self):
        packages = [entry.get('name') for entry in self.getSupportedEntries()]
        extras = [data for data in list(self.installed.items())
                  if data[0] not in packages]
        return [Bcfg2.Client.XML.Element('Package', name=name,
                                         type=self.pkgtype, version=version)
                for (name, version) in extras]
    FindExtra.__doc__ = Tool.FindExtra.__doc__


class SvcTool(Tool):
    """ Base class for tools that handle Service entries """

    def __init__(self, logger, setup, config):
        Tool.__init__(self, logger, setup, config)
        #: List of services that have been restarted
        self.restarted = []
    __init__.__doc__ = Tool.__init__.__doc__

    def get_svc_command(self, service, action):
        """ Return a command that can be run to start or stop a service.

        :param service: The service entry to modify
        :type service: lxml.etree._Element
        :param action: The action to take (e.g., "stop", "start")
        :type action: string
        :returns: string - The command to run
        """
        return '/etc/init.d/%s %s' % (service.get('name'), action)

    def start_service(self, service):
        """ Start a service.

        :param service: The service entry to modify
        :type service: lxml.etree._Element
        :returns: tuple - The return value from
                  :class:`Bcfg2.Client.Tools.Executor.run`
        """
        self.logger.debug('Starting service %s' % service.get('name'))
        return self.cmd.run(self.get_svc_command(service, 'start'))[0]

    def stop_service(self, service):
        """ Stop a service.

        :param service: The service entry to modify
        :type service: lxml.etree._Element
        :returns: tuple - The return value from
                  :class:`Bcfg2.Client.Tools.Executor.run`
        """
        self.logger.debug('Stopping service %s' % service.get('name'))
        return self.cmd.run(self.get_svc_command(service, 'stop'))[0]

    def restart_service(self, service):
        """ Restart a service.

        :param service: The service entry to modify
        :type service: lxml.etree._Element
        :returns: tuple - The return value from
                  :class:`Bcfg2.Client.Tools.Executor.run`
        """
        self.logger.debug('Restarting service %s' % service.get('name'))
        restart_target = service.get('target', 'restart')
        return self.cmd.run(self.get_svc_command(service, restart_target))[0]

    def check_service(self, service):
        """ Check the status a service.

        :param service: The service entry to modify
        :type service: lxml.etree._Element
        :returns: bool - True if the status command returned 0, False
                  otherwise
        """
        return self.cmd.run(self.get_svc_command(service, 'status'))[0] == 0

    def Remove(self, services):
        if self.setup['servicemode'] != 'disabled':
            for entry in services:
                entry.set("status", "off")
                self.InstallService(entry)
    Remove.__doc__ = Tool.Remove.__doc__

    def BundleUpdated(self, bundle, states):
        if self.setup['servicemode'] == 'disabled':
            return

        for entry in [ent for ent in bundle if self.handlesEntry(ent)]:
            restart = entry.get("restart", "true")
            if (restart.lower() == "false" or
                (restart.lower() == "interactive" and
                 not self.setup['interactive'])):
                continue

            rv = None
            if entry.get('status') == 'on':
                if self.setup['servicemode'] == 'build':
                    rv = self.stop_service(entry)
                elif entry.get('name') not in self.restarted:
                    if self.setup['interactive']:
                        prompt = ('Restart service %s?: (y/N): ' %
                                  entry.get('name'))
                        # flush input buffer
                        while len(select.select([sys.stdin.fileno()], [], [],
                                                0.0)[0]) > 0:
                            os.read(sys.stdin.fileno(), 4096)
                        ans = input(prompt)
                        if ans not in ['y', 'Y']:
                            continue
                    rv = self.restart_service(entry)
                    if not rv:
                        self.restarted.append(entry.get('name'))
            else:
                rv = self.stop_service(entry)
            if rv:
                self.logger.error("Failed to manipulate service %s" %
                                  (entry.get('name')))
    BundleUpdated.__doc__ = Tool.BundleUpdated.__doc__

    def Install(self, entries, states):
        install_entries = []
        for entry in entries:
            if entry.get('install', 'true').lower() == 'false':
                self.logger.info("Service %s installation is false. Skipping "
                                 "installation." % (entry.get('name')))
            else:
                install_entries.append(entry)
        return Tool.Install(self, install_entries, states)
    Install.__doc__ = Tool.Install.__doc__

    def InstallService(self, entry):
        """ Install a single service entry.  See
        :func:`Bcfg2.Client.Tools.Tool.Install`.

        :param entry: The Service entry to install
        :type entry: lxml.etree._Element
        :returns: bool - True if installation was successful, False
                  otherwise
        """
        raise NotImplementedError
