#!/usr/bin/env python

# $1 is the path to the directory to sync
# $2 is the name of the remote container to use

# If the environment variable PUSH_NO_CHECKSUM is set, then checksum
# verification is skipped.

import argparse
import datetime
import json
import os
import re
import sys
import time

import utility

import local


has_pyrax = False
try:
    import remote_pyrax
    has_pyrax = True
except ImportError, e:
    print ('%s Could not import pyrax drivers: %s'
           %(datetime.datetime.now(), e))


has_libcloud = False
try:
    import remote_libcloud
    has_libcloud = True
except ImportError, e:
    print ('%s Could not import libcloud drivers: %s'
           %(datetime.datetime.now(), e))


uploaded = 0
destination_total = 0

ARGS = None


def transfer_directory(source_container, destination_container, path, refilter):
    global uploaded
    global destination_total

    print '%s Syncing %s' %(datetime.datetime.now(), path)
    source_dir = source_container.get_directory(path)
    destination_dir = destination_container.get_directory(path)

    queued_shas = {}
    for ent in source_dir.listdir():
        # NOTE(mikal): this is a work around to handle the historial way
        # in which the directory name appears in both the container name and
        # path inside the container for remote stores. It was easier than
        # rewriting the contents of the remote stores.
        if source_dir.region != 'local':
            ent = '/'.join(os.path.split(ent)[1:])

        fullpath = utility.path_join(path, ent)
        source_file = source_dir.get_file(ent)

        if source_file.isdir():
            transfer_directory(source_container, destination_container,
                               fullpath, refilter)

        elif source_file.islink():
            pass

        elif source_file.get_path().endswith('.sha512'):
            pass

        elif source_file.get_path().endswith('.shalist'):
            pass

        elif source_file.get_path().endswith('~'):
            pass

        else:
            destination_file = destination_dir.get_file(ent)
            print '%s Consider  %s' %(datetime.datetime.now(),
                                      source_file.get_path())
            m = refilter.match(source_file.get_path())
            if not m:
                print '%s ... skipping due to filter' % datetime.datetime.now()
                continue

            if destination_file.exists():
                if int(os.environ.get('PUSH_NO_CHECKSUM', 0)) == 1:
                    print '%s ... skipping checksum' % datetime.datetime.now()
                    if ARGS.delete_local:
                        print ('%s ... cleaning up file'
                               % datetime.datetime.now())
                        os.remove(source_file.get_path())
                    continue

                if destination_file.checksum() != source_file.checksum():
                    print ('%s Checksum for %s does not match! (%s vs %s)'
                           %(datetime.datetime.now(), source_file.get_path(),
                             source_file.checksum(),
                             destination_file.checksum()))
                else:
                    if ARGS.delete_local:
                        print ('%s ... cleaning up file'
                               % datetime.datetime.now())
                        os.remove(source_file.get_path())
                    continue

            done = False
            attempts = 0
            while not done and attempts < 3:
                try:
                    local_file = source_file.get_path()
                    local_cleanup = False
                    if not source_file.region == 'local':
                        print ('%s Fetching the file from remote location'
                               % datetime.datetime.now())
                        local_cleanup = True
                        local_file = source_file.fetch()

                    source_size = source_file.size()
                    print ('%s Transferring %s (%s)'
                           %(datetime.datetime.now(), source_file.get_path(),
                             utility.DisplayFriendlySize(source_size)))
                    start_time = time.time()
                    destination_file.store(local_file)

                    queued_shas[source_file.checksum()] = destination_file
                    print ('%s There are %d queued checksum writes'
                           %(datetime.datetime.now(), len(queued_shas)))

                    if ARGS.delete_local:
                        print ('%s ... cleaning up file'
                               % datetime.datetime.now())
                        os.remove(source_file.get_path())

                    if len(queued_shas) > 20 or source_size > 1024 * 1024:
                        print ('%s Clearing queued checksum writes'
                               % datetime.datetime.now())
                        for sha in queued_shas:
                            destination_dir.update_shalist(
                                queued_shas[sha].path, sha)
                        destination_dir.write_shalist()
                        queued_shas = {}

                    if local_cleanup:
                        os.remove(local_file)

                    print ('%s Uploaded  %s (%s)'
                           %(datetime.datetime.now(), source_file.get_path(),
                             utility.DisplayFriendlySize(source_file.size())))
                    uploaded += source_size
                    destination_total += source_size
                    elapsed = time.time() - start_time
                    print ('%s Total     %s'
                           %(datetime.datetime.now(),
                             utility.DisplayFriendlySize(uploaded)))
                    print ('%s           %s per second'
                           %(datetime.datetime.now(),
                             utility.DisplayFriendlySize(int(source_size /
                                                             elapsed))))
                    print ('%s Stored    %s'
                           %(datetime.datetime.now(),
                             utility.DisplayFriendlySize(destination_total)))
                    done = True

                except Exception, e:
                    sys.stderr.write('%s Sync failed for %s (attempt %d): %s'
                                     %(datetime.datetime.now(),
                                       source_file.get_path(),
                                       attempts, e))
                    attempts += 1

    print '%s Clearing trailing checksum writes' % datetime.datetime.now()
    for sha in queued_shas:
        for sha in queued_shas:
            destination_dir.update_shalist(queued_shas[sha].path, sha)
        destination_dir.write_shalist()
    queued_shas = {}


REMOTE_RE = re.compile('[a-z]+://')
LIBCLOUD_RE = re.compile('[a-z0-9]+@[a-z_]+://')


def get_container(url):
    remote_match = REMOTE_RE.match(url)
    libcloud_match = LIBCLOUD_RE.match(url)

    if url.startswith('file://'):
        return local.LocalContainer(url)
    elif remote_match and has_pyrax:
        return remote_pyrax.RemoteContainer(url)
    elif libcloud_match and has_libcloud:
        return remote_libcloud.RemoteContainer(url)
    else:
        print 'Unknown container URL format'
        sys.exit(1)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('-d', '--delete-local', default=False,
                        action='store_true',
                        help='Should we delete local files?')
    parser.add_argument('-f', '--filter', default='.*',
                        help='Optional regexp filter')
    parser.add_argument('source')
    parser.add_argument('destination')
    ARGS = parser.parse_args()

    print '%s Running with "%s"' %(datetime.datetime.now(), ' '.join(sys.argv))

    source_container = get_container(ARGS.source)
    destination_container = get_container(ARGS.destination)
    refilter = ARGS.filter

    transfer_directory(source_container, destination_container, None,
                       re.compile(refilter))

    print '%s Finished' % datetime.datetime.now()
    print '%s Total     %s' %(datetime.datetime.now(),
                              utility.DisplayFriendlySize(uploaded))

