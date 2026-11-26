#!/usr/bin/env python3
"""
camera_scan.py

DECXIN Fisheye Camera Manager CLI

Usage:
    camera_scan list
    camera_scan init
    camera_scan update
    camera_scan check
    camera_scan resolve <alias>
    camera_scan doctor
"""

from __future__ import annotations

import argparse
import sys

try:
    from .scanner import CameraScanner
    from .resolver import CameraResolver
    from .yaml_manager import CameraYamlManager
except ImportError:
    from scanner import CameraScanner
    from resolver import CameraResolver
    from yaml_manager import CameraYamlManager


class CameraScanCLI:

    def __init__(self):

        self.scanner = CameraScanner()

        self.yaml = CameraYamlManager()

        self.resolver = CameraResolver()

    ############################################################
    # list
    ############################################################

    def cmd_list(self, args):

        cameras = self.scanner.scan()

        aliases = {}

        for alias, config in self.yaml.load().items():

            current = aliases.get(config.usb_path)

            aliases[config.usb_path] = (
                alias if current is None else f"{current},{alias}"
            )

        self.scanner.print_table(cameras, aliases)

    ############################################################
    # init
    ############################################################

    def cmd_init(self, args):

        append = False

        if self.yaml.exists():

            print("Configuration already exists.")
            print("1. Add new cameras only")
            print("2. Overwrite and recreate")
            print("q. Cancel")

            ans = input("Select [1/2/q]: ").strip().lower()

            if ans == "1":

                append = True

            elif ans == "2":

                append = False

            else:

                print("Cancelled.")

                return

        cameras = self.scanner.scan()

        aliases = {}

        if append:

            for alias, config in self.yaml.load().items():

                aliases[config.usb_path] = alias

        self.scanner.print_table(cameras, aliases)

        self.yaml.interactive_create(cameras, append=append)

    ############################################################
    # update
    ############################################################

    def cmd_update(self, args):

        cameras = self.scanner.scan()

        self.yaml.update(cameras)

    ############################################################
    # check
    ############################################################

    def cmd_check(self, args):

        self.resolver.check()

    ############################################################
    # resolve
    ############################################################

    def cmd_resolve(self, args):

        dev = self.resolver.resolve(args.alias)

        if dev is None:

            sys.exit(1)

        print(dev)

    ############################################################
    # doctor
    ############################################################

    def cmd_doctor(self, args):

        self.resolver.doctor()


##########################################################################
#
# parser
#
##########################################################################

def build_parser():

    parser = argparse.ArgumentParser(
        prog="camera_scan.py",
        description="DECXIN fisheye camera manager"
    )

    sub = parser.add_subparsers(dest="command")

    ###########################################################

    sub.add_parser(
        "list",
        help="List DECXIN fisheye cameras"
    )

    ###########################################################

    sub.add_parser(
        "init",
        help="Create cameras.yaml"
    )

    ###########################################################

    sub.add_parser(
        "update",
        help="Update cameras.yaml"
    )

    ###########################################################

    sub.add_parser(
        "check",
        help="Check configuration"
    )

    ###########################################################

    p = sub.add_parser(
        "resolve",
        help="Resolve alias"
    )

    p.add_argument(
        "alias",
        help="camera alias"
    )

    ###########################################################

    sub.add_parser(
        "doctor",
        help="Diagnostic"
    )

    return parser


##########################################################################
#
# main
#
##########################################################################

def main():

    parser = build_parser()

    args = parser.parse_args()

    if args.command is None:

        parser.print_help()

        return

    cli = CameraScanCLI()

    table = {

        "list": cli.cmd_list,

        "init": cli.cmd_init,

        "update": cli.cmd_update,

        "check": cli.cmd_check,

        "resolve": cli.cmd_resolve,

        "doctor": cli.cmd_doctor,

    }

    table[args.command](args)


if __name__ == "__main__":

    main()
