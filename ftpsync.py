"""
Synchonization over FTP. Files to synchronize specified in a list of file specifications.
"""


import os
import re
import glob
import ftplib
import datetime
import argparse
import configparser
import hashlib
import io
import tempfile
from functools import cache

from icecream import ic


DIFF = r'"c:\Program Files\WinMerge\WinMergeU.exe"'


@cache
def cachedir():
    tempdir = tempfile.gettempdir()
    cache_dir = os.path.join(tempdir, 'ftpsync')
    if not os.path.exists(cache_dir):
        os.makedirs(cache_dir)
    return cache_dir


def read_spec(root, liste):
    return [os.path.join(root, line) for line in liste]


def test_connection(server, user, pwd):
    try:
        with ftplib.FTP(server, user, pwd) as ftp:
            return True
    except:
        return False


def list_local(directory, spec):
    speclist = read_spec(directory, spec)
    ic(speclist)
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
    ic(directory)
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


def list_remote_one(server, user, pwd, directory, basedir, flat:bool=False):
    ic(basedir)
    with ftplib.FTP(server, user, pwd) as ftp:
        if flat:
            full_list = list_remote_dir_flat(ftp, directory)
        else:
            full_list = list_remote_dir(ftp, directory)

    remote = {}
    for fn, descr in full_list:
        relname = os.path.relpath(fn, basedir)
        remote[relname] = {'size': int(descr['size']), 'modify': descr['modify'], 'fullname': fn}

    return remote


def list_remote(server, user, pwd, remspec):
    """
    `remspec` is a list of paths separated with "|". If a path is terminated
    with * (by default), its sub directories are ignored. If a path is terminated
    with **, its sub directories are scanned recursively. The paths of returned
    files are given relatively to first path in `remspec`.
    """
    baseremdir = re.sub(r'/\*+', '', remspec.split('|')[0])
    ic(baseremdir)
    remote = {}
    for remdir in remspec.split('|'):
        flat = not remdir.endswith('/**')
        remdir = re.sub(r'/\*+', '', remdir)
        ic(flat, remdir)
        remote.update(list_remote_one(server, user, pwd, remdir, baseremdir, flat))
    return remote


def compare_hashcode(locfn, remfn, server, user, pwd):
    with open(locfn, 'rb') as f:
        locmd5 = hashlib.md5(f.read()).hexdigest()

    with ftplib.FTP(server, user, pwd) as ftp:
        with io.BytesIO() as fp:
            ftp.retrbinary(f'RETR {remfn}', fp.write)
            remmd5 = hashlib.md5(fp.getvalue()).hexdigest()

    print(os.path.basename(locfn), locmd5, remmd5)
    return locmd5 == remmd5


def difference(locdir, project_files, server, user, pwd, remspec):
    print(project_files)
    local = list_local(locdir, project_files)
    remote = list_remote(server, user, pwd, remspec)
    # ic(local.keys())
    # ic(remote.keys())

    offsync = []
    missing = []
    extra = []
    for fn, descr in local.items():
        if fn not in remote:
            missing.append(fn)
        else:
            descr2 = remote[fn]
            if descr['size'] == descr2['size'] and descr['modify'] <= descr2['modify']:
                # no doubts
                pass
            elif descr['size'] == descr2['size']:
                if 1 or fn.endswith('.html'):
                    if compare_hashcode(descr["fullname"], descr2["fullname"], server, user, pwd):
                        pass
                    else:
                        offsync.append(fn)
                else:
                    offsync.append(fn)
            else:
                offsync.append(fn)

    for fn, descr in remote.items():
        if fn not in local:
            extra.append(fn)

    return local, remote, offsync, missing, extra


def user_check(local, remote, offsync, server, user, pwd):
    prompt = '[' + ', '.join(['q'] + [str(_) for _ in range(1, len(offsync) + 1)]) + '] ? '
    while 1:
        inpt = input(prompt)
        if inpt == 'q':
            break
        fn = offsync[int(inpt) - 1]
        loc = local[fn]
        rem = remote[fn]
        with ftplib.FTP(server, user, pwd) as ftp:
            dnload = os.path.join(cachedir(), os.path.basename(fn))
            with open(dnload, 'wb') as fp:
                ftp.retrbinary('RETR %s' % rem['fullname'], fp.write)
        os.system(f'{DIFF} {loc["fullname"]} {dnload}')


def main_list(local, remote, offsync, missing, extra, server, user, pwd, file=None):
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
        for index, fn in enumerate(offsync, 1):
            loc = local[fn]
            rem = remote[fn]
            print('    ', index, fn,
                f'(size: {loc["size"]} --> {rem["size"]},',
                f'{loc["modify"]} --> {rem["modify"]})',
                file=file)
        user_check(local, remote, offsync, server, user, pwd)


def main_update(local, remote, offsync, missing, extra, server, user, pwd, remotedir):
    with ftplib.FTP(server, user, pwd) as ftp:

        if missing:
            print('Copy missing files to server')
            for fn in missing:
                print('    ', local[fn]['fullname'])
                with open(local[fn]['fullname'], 'rb') as f:
                    print(f'STOR {remotedir}/%s' % fn.replace('\\', '/'), f)
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
    args = parser.parse_args()

    config = configparser.ConfigParser(
        delimiters='=',
        interpolation=configparser.ExtendedInterpolation()
    )
    config.read(args.project)

    args.server = config.get('ftp', 'server', fallback=None)
    args.user = config.get('ftp', 'user', fallback=None)
    args.remotedir = config.get('ftp', 'remotedir', fallback=None)
    x = config.get('ftp', 'project', fallback=None)
    args.project = [line for line in x.strip().splitlines()]
    # ftp pwd entered by user
    args.pwd = None
    args.pwd = input('FTP password: ')

    return parser, args


def main():
    parser, args = parse_command_line()

    local, remote, offsync, missing, extra = difference(
        args.localdir,
        args.project,
        args.server,
        args.user,
        args.pwd,
        args.remotedir
    )

    if args.list:
        main_list(local, remote, offsync, missing, extra, args.server, args.user, args.pwd)
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
