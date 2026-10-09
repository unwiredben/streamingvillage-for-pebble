# Copyright (c) 2026 Ben Combee
# SPDX-License-Identifier: MIT
import json
import shutil

from waflib import Logs

top = '.'
out = 'build'


def options(ctx):
    ctx.load('pebble_sdk')


def configure(ctx):
    ctx.load('pebble_sdk')


def copy_versioned_bundle(ctx):
    with open(ctx.path.find_node('package.json').abspath()) as manifest:
        package = json.load(manifest)
    source = ctx.bldnode.make_node(ctx.env.BUNDLE_NAME).abspath()
    filename = '{}-{}.pbw'.format(package['name'], package['version'])
    destination = ctx.path.make_node(filename).abspath()
    shutil.copyfile(source, destination)
    Logs.info('Copied build bundle to {}'.format(filename))


def build(ctx):
    ctx.load('pebble_sdk')

    binaries = []
    cached_env = ctx.env
    for platform in ctx.env.TARGET_PLATFORMS:
        ctx.env = ctx.all_envs[platform]
        ctx.set_group(ctx.env.PLATFORM_NAME)
        app_elf = '{}/pebble-app.elf'.format(ctx.env.BUILD_DIR)
        ctx.pbl_build(source=ctx.path.ant_glob('src/c/**/*.c'),
                      target=app_elf,
                      bin_type='app')
        binaries.append({'platform': platform, 'app_elf': app_elf})
    ctx.env = cached_env

    ctx.set_group('bundle')
    ctx.pbl_bundle(binaries=binaries, js=[])
    ctx.add_post_fun(copy_versioned_bundle)
