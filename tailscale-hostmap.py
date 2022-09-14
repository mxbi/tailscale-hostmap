#!/bin/env python3
"""Map tailscale hosts into /etc/hosts."""
import argparse
import datetime
import json
import os
import re
import subprocess
import sys
import typing
from dataclasses import dataclass
from pathlib import Path

args = None
HOSTS_BEGIN = "# tailscale-hostmap begin"
HOSTS_END = "# tailscale-hostmap end"


def is_ip4(addr: str) -> bool:
    """Check for ip4 address."""
    # tailscale all start with 100
    return addr.startswith("100")


def is_valid_host(hostname: str) -> bool:
    """Check host name is valid."""
    return hostname != "device-of-shared-to-user"


def is_valid_addr(addr: str) -> bool:
    """Check address is valid."""
    if args.ip4 or args.ip6:
        return args.ip4 if is_ip4(addr) else args.ip6
    else:
        return True

@dataclass
class PeerInfo:
    """Information about tailscale peers."""

    host: str
    addr: str
    comments: typing.List[str]

    def hostname(self) -> str:
        """Compose hostname with domain extension."""
        return f"{self.host}.{args.domain}" if args.domain else self.host

    def comment_str(self) -> str:
        """Flatten comments into string."""
        return "# {}".format(", ".join(self.comments)) if self.comments else ""

    def host_line(self, fmt_str: str) -> str:
        """Format as host line."""
        return fmt_str.format(self.addr, self.hostname(), self.comment_str())

    def is_valid(self) -> bool:
        """Check if peer matches spec."""
        return is_valid_host(self.host) and is_valid_addr(self.addr)


def valid_peers(
    peers: typing.List[PeerInfo],
) -> typing.Generator[typing.Union[PeerInfo, None], None, None]:
    """Generate valid peers."""
    return (pr for pr in peers if pr.is_valid())


def tailscale_peers() -> typing.List[PeerInfo]:
    """Get peer info from tailscale."""
    # query tailscale
    status = json.loads(
        subprocess.check_output([args.ts_binary, "status", "--json"])
    )

    # To check for shared machines, we exclude any machines owned by other users
    # This could be an issue with team tailscale, but I can't test it right now, so let me know.
    self_uid = status["Self"]["UserID"]

    def valid_status() -> typing.Generator[
        typing.Dict[str, typing.Any], None, None
    ]:
        """Iterate valid peers."""
        return (
            pr
            for pr in status["Peer"].values()
            if args.include_shared or pr["UserID"] == self_uid
        )

    peers = []
    # run my peers
    for peer in valid_status():
        peer_uid = peer["UserID"]

        # ip4 and ip6...
        peers.extend(
            PeerInfo(
                peer["HostName"].lower(),
                ipaddr,
                ["shared"] if peer_uid != self_uid else [],
            )
            for ipaddr in peer["TailscaleIPs"]
        )

    return peers

def format_hosts_lines(peers: typing.List[PeerInfo]) -> typing.List[str]:
    """Format peers into lines for /etc/hosts."""
    # line-up columns
    if len(valid_peers(peers)):
        maxaddr = max(len(peer.addr) for peer in valid_peers(peers))
        maxhost = max(len(peer.hostname()) for peer in valid_peers(peers))
        fmt_str = f"{{:<{maxaddr}}}\t{{:<{maxhost}}}\t{{}}"

    return (
        [
            HOSTS_BEGIN,
            f"# modified {datetime.datetime.now().isoformat()}",
        ]
        + [peer.host_line(fmt_str) for peer in valid_peers(peers)]
        + [HOSTS_END]
    )


def update_hosts(hosts_lines: typing.List[str]) -> typing.List[str]:
    """Update hosts file with tailscale peers."""
    # read old file
    old_etc_hosts = Path(args.hosts_file).read_text(encoding="utf-8")

    # remove old entries
    new_etc_hosts = re.sub(
        rf"{HOSTS_BEGIN}.*{HOSTS_END}",
        "",
        old_etc_hosts,
        flags=re.S,
    )

    # add new entries
    new_etc_hosts += "\n".join(hosts_lines)

    # stage "new" file
    new_file = f"{args.hosts_file}.tailscale-hostmap"
    with open(new_file, "w", encoding="utf-8") as f_hostmap:
        f_hostmap.write(new_etc_hosts)

    # BIG - mv "new" file over "old" file
    # RACE CONDITION - POSSIBLE DATA LOSS
    os.rename(new_file, args.hosts_file)

    return hosts_lines


def main(argv: typing.List[str] = None) -> int:
    """Run program."""
    if not argv:
        argv = sys.argv
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--domain",
        default=False,
        help="The domain to append to the hostname. For example, `pi` becomes `pi.ts` when domain=`ts`. Defaults to no domain",
    )
    parser.add_argument(
        "-s",
        "--include-shared",
        default=False,
        action="store_true",
        help="Add this flag to also include shared machines in DNS",
    )
    parser.add_argument(
        "--ts-binary",
        default="/usr/bin/tailscale",
        help="The location of the tailscale binary to call. Defaults to /usr/bin/tailscale",
    )
    parser.add_argument(
        "-ip4",
        "--ip4",
        default=False,
        action="store_true",
        help="Add this flag to limit processing to ip4 addresses",
    )
    parser.add_argument(
        "-ip6",
        "--ip6",
        default=False,
        action="store_true",
        help="Add this flag to limit processing to ip6 addresses",
    )
    parser.add_argument(
        "--hosts-file",
        default="/etc/hosts",
        help="The location of the hosts file to update. Defaults to /etc/hosts",
    )
    global args
    args = parser.parse_args()

    # do the update
    hosts_lines = update_hosts(format_hosts_lines(tailscale_peers()))

    # report status
    me = Path(argv[0]).resolve()
    print("\n".join(hosts_lines))
    print("Add this line to /etc/crontab to run this script automatically:")
    print(f"*/5 * * * * /usr/bin/python3 {me} --domain ts -s")

    return 0


if __name__ == "__main__":
    sys.exit(main())
