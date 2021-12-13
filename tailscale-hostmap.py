#!/bin/env python3

import json
import argparse
import subprocess
import re
import os
import datetime

def parse_entries():
    output = subprocess.check_output([args.ts_binary, "status", "--json"])
    
    status = json.loads(output)

    # To check for shared machines, we exclude any machines owned by other users
    # This could be an issue with team tailscale, but I can't test it right now, so let me know.
    self_uid = status['Self']['UserID']

    peers = []
    for peer in status['Peer'].values():
      comments = []
      peer_uid = peer['UserID']

      if args.include_shared or peer_uid == self_uid:
        peer_hostname = peer['HostName'].lower() # Hostnames are case insensitive

        if peer_uid != self_uid:
          comments.append('shared')

        peer_addr = peer['TailAddr']
        # print(peer_hostname, peer_addr)
        peers.append({'host': peer_hostname, 'addr': peer_addr, 'comments': comments})

    return peers

def update_hosts(peers):
  # Create a string to insert into /etc/hosts
  hosts_insert = '# tailscale-hostmap begin\n'
  hosts_insert += '# modified {}\n'.format(datetime.datetime.now().isoformat())
  for peer in peers:
    hostname = peer['host']
    
    # This isn't a real device, don't create DNS entries
    if hostname == 'device-of-shared-to-user':
      continue
    
    if args.domain:
      hostname += '.' + args.domain
    hosts_insert += '{}\t{}\t{}\n'.format(peer['addr'], hostname, '# {}'.format(', '.join(peer['comments'])) if peer['comments'] else '')
  hosts_insert += '# tailscale-hostmap end\n'

  print(hosts_insert)

  # Remove current hostmap entries from /etc/hosts
  # Yes, there is a TOCTOU race condition here - if another client edits the /etc/hosts in the meantime it could be overwritten, but this is very unlikely
  # Sorry!
  old_etc_hosts = open('/etc/hosts', 'r').read()
  new_etc_hosts = re.sub(r'# tailscale-hostmap begin.*# tailscale-hostmap end\n', '', old_etc_hosts, flags=re.S)
  new_etc_hosts += hosts_insert

  open('{}.tailscale-hostmap'.format(args.hosts_file), 'w').write(new_etc_hosts)
  os.rename('{}.tailscale-hostmap'.format(args.hosts_file), '{}'.format(args.hosts_file))


if __name__ == '__main__':
  parser = argparse.ArgumentParser()
  parser.add_argument("--domain", default=False, help="The domain to append to the hostname. For example, `pi` becomes `pi.ts` when domain=`ts`. Defaults to no domain")
  parser.add_argument("-s", "--include-shared", default=False, action="store_true", help="Add this flag to also include shared machines in DNS")
  parser.add_argument("--ts-binary", default="/usr/bin/tailscale", help="The location of the tailscale binary to call. Defaults to /usr/bin/tailscale")
  parser.add_argument("--hosts-file", default="/etc/hosts", help="The location of the hosts file to update. Defaults to /etc/hosts")
  args = parser.parse_args()

  peers = parse_entries()
  update_hosts(peers)
