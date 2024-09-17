#!/usr/bin/env python3

from setuptools import setup

META_ENTRY_POINT = 'ovos-metadata-test-plugin=metadata_test:MetadataPlugin'

setup(
    name="ovos-metadata-test-plugin",
    description='OpenVoiceOS metadata test Plugin',
    version="0.0.1",
    author_email='jarbasai@mailfence.com',
    license='apache-2.0',
    packages=["metadata_test"],
    include_package_data=True,
    zip_safe=True,
    classifiers=[
        'Development Status :: 3 - Alpha',
        'Intended Audience :: Developers',
        'Topic :: Text Processing :: Linguistic',
        'License :: OSI Approved :: Apache Software License',
        'Programming Language :: Python :: 3.4',
        'Programming Language :: Python :: 3.5',
        'Programming Language :: Python :: 3.6',
    ],
    entry_points={
        'neon.plugin.metadata': META_ENTRY_POINT
    }
)
