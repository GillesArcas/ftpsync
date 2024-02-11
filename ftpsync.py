"""
Synchonization over FTP. Files to synchronize specified in a file with tree structure.
"""


import sys
import os
import re
import glob
import ftplib
import datetime
import argparse
from itertools import pairwise


def read_spec(root, liste):
    speclist = []
    # check indentation and store levels
    levels = []
    for iline, line in enumerate(liste, 1):
        match = re.match(r' *', line)
        spaces = match[0]
        if len(spaces) % 4 != 0:
            print('indent pas multiple de 4 ligne', iline)
            sys.exit(1)
        levels.append(len(spaces) // 4)

    # check positive indent
    for iline, (level1, level2) in enumerate(pairwise(levels), 1):
        if level2 > level1 and level2 - level1 > 1:
            print('trop indentation ligne', iline + 1)

    path = [root]
    for iline, (line, linelevel) in enumerate(zip(liste, levels)):
        spec = line.strip()
        path = path[:linelevel + 1]
        if iline < len(liste) - 1 and levels[iline + 1] == linelevel + 1:
            # current line is directory
            path.append(spec)
        else:
            # current line is file
            speclist.append(os.path.join(*path, spec))
    return speclist


def test_connection(server, user, pwd):
    try:
        with ftplib.FTP(server, user, pwd) as ftp:
            return True
    except:
        return False


def list_local(directory, specname):
    with open(specname, encoding='utf-8') as f:
        liste = f.readlines()

    speclist = read_spec(directory, liste)
    name_list = []
    for spec in speclist:
        if os.path.basename(spec) == '*':
            liste = [_ for _ in glob.glob(spec) if os.path.isfile(_)]
        elif os.path.basename(spec) == '**':
            liste = [_ for _ in glob.glob(spec, recursive=True) if os.path.isfile(_)]
        else:
            liste = glob.glob(spec)
        name_list.extend(liste)


    local = {}
    for fn in name_list:
        relname = os.path.relpath(fn, directory)
        t = os.path.getmtime(fn)
        dt = datetime.datetime.strftime(datetime.datetime.fromtimestamp(t), "%Y%m%d%H%M%S")
        local[relname] = {'size': os.path.getsize(fn), 'modify': dt, 'fullname': fn}

    return local


def list_remote_dir_flat(ftp, directory):
    full_list = []
    liste = list(ftp.mlsd(directory))
    for name, descr in liste:
        if descr['type'] == 'file':
            full_list.append((f'{directory}/{name}', descr))
    return full_list


def list_remote_dir(ftp, directory):
    full_list = []
    liste = list(ftp.mlsd(directory))
    for name, descr in liste:
        if descr['type'] == 'file':
            full_list.append((f'{directory}/{name}', descr))
        if descr['type'] == 'dir':
            L = list_remote_dir(ftp, f'{directory}/{name}')
            full_list.extend(L)

    return full_list


def list_remote(server, user, pwd, directory, flat:bool=False):
    with ftplib.FTP(server, user, pwd) as ftp:
        if flat:
            full_list = list_remote_dir_flat(ftp, directory)
        else:
            full_list = list_remote_dir(ftp, directory)

    remote = {}
    for fn, descr in full_list:
        relname = os.path.relpath(fn, directory)
        remote[relname] = {'size': int(descr['size']), 'modify': descr['modify'], 'fullname': fn}

    return remote


def difference(locdir, project_files, server, user, pwd, remdir, flat:bool=False):
    local = list_local(locdir, project_files)
    remote = list_remote(server, user, pwd, remdir, flat)

    offsync = []
    missing = []
    extra = []
    for fn, descr in local.items():
        if fn not in remote:
            missing.append(fn)
        else:
            descr2 = remote[fn]
            if descr['size'] != descr2['size'] or descr['modify'] > descr2['modify']:
                offsync.append(fn)

    for fn, descr in remote.items():
        if fn not in local:
            extra.append(fn)

    return local, remote, offsync, missing, extra


def main_list(local, remote, offsync, missing, extra, file=None):
    if offsync == missing == extra == []:
        print('Remote is up to date')

    if missing:
        print('Missing', file=file)
        for fn in missing:
            print('    ', fn, file=file)
    if extra:
        print(file=file)
        print('Extra', file=file)
        for fn in extra:
            print('    ', fn, file=file)
    if offsync:
        print(file=file)
        print('Off sync', file=file)
        for fn in offsync:
            loc = local[fn]
            rem = remote[fn]
            print('    ', fn,
                f'(size: {loc["size"]} --> {rem["size"]},',
                f'{loc["modify"]} --> {rem["modify"]})',
                file=file)


def main_update(local, remote, offsync, missing, extra, server, user, pwd, remotedir):
    with ftplib.FTP(server, user, pwd) as ftp:

        if missing:
            print('Copy missing files to server')
            for fn in missing:
                print('    ', local[fn]['fullname'])
                with open(local[fn]['fullname'], 'rb') as f:
                    ftp.storbinary(f'STOR {remotedir}/%s' % fn.replace('\\', '/'), f)

        if extra:
            print()
            print('Removing extra files from server')
            for fn in extra:
                print('    ', remote[fn]['fullname'])
                ftp.delete(remote[fn]['fullname'])

        if offsync:
            print()
            print('Copy off sync files to server')
            for fn in offsync:
                print('    ', remote[fn]['fullname'])
                with open(local[fn]['fullname'], 'rb') as f:
                    ftp.storbinary('STOR ' + remote[fn]['fullname'], f)


def parse_command_line():
    parser = argparse.ArgumentParser(add_help=True, usage=__doc__)
    xgroup = parser.add_mutually_exclusive_group()
    xgroup.add_argument('--list', action='store_true', default=False)
    xgroup.add_argument('--update', action='store_true', default=False)
    parser.add_argument(action='store', dest='localdir')
    parser.add_argument(action='store', dest='project')
    parser.add_argument(action='store', dest='server')
    parser.add_argument(action='store', dest='user')
    parser.add_argument(action='store', dest='pwd')
    parser.add_argument(action='store', dest='remotedir')
    parser.add_argument(action='store', dest='flat', nargs='?', choices=('flat', 'rec'), default='rec')
    args = parser.parse_args()
    return parser, args


def main():
    parser, args = parse_command_line()

    local, remote, offsync, missing, extra = difference(
        args.localdir,
        args.project,
        args.server,
        args.user,
        args.pwd,
        args.remotedir,
        args.flat == 'flat'
    )

    if args.list:
        main_list(local, remote, offsync, missing, extra)
    elif args.update:
        main_update(
            local, remote, offsync, missing, extra,
            args.server,
            args.user,
            args.pwd,
            args.remotedir
        )
    else:
        parser.print_help()


if __name__ == '__main__':
    main()
