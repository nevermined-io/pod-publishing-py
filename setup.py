#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""The setup script."""

from setuptools import find_packages, setup

with open("README.md") as readme_file:
    readme = readme_file.read()

install_requirements = [
    "nevermined-sdk-py==0.4.0",
    "web3==5.9.0",
    "minio==6.0.0",
]

# Required to run setup.py:
setup_requirements = []

test_requirements = []

dev_requirements = []

docs_requirements = []

setup(
    author="nevermined-io",
    author_email="root@nevermined.io",
    classifiers=[
        "Development Status :: 2 - Pre-Alpha",
        "Intended Audience :: Developers",
        "License :: OSI Approved :: Apache Software License",
        "Natural Language :: English",
        "Programming Language :: Python :: 3.6",
    ],
    description="🐳 Nevermined/Python pod publishing",
    extras_require={
        "test": test_requirements,
        "dev": dev_requirements + test_requirements + docs_requirements,
        "docs": docs_requirements,
    },
    install_requires=install_requirements,
    license="Apache Software License 2.0",
    long_description=readme,
    long_description_content_type="text/markdown",
    include_package_data=True,
    keywords="nevermined-pod-publishing",
    name="nevermined-pod-publishing",
    packages=find_packages(),
    setup_requires=setup_requirements,
    tests_require=test_requirements,
    url="https://github.com/nevermined-io/pod-publishing-py",
    version="0.1.1",
    zip_safe=False,
    entry_points={
        "console_scripts": ["pod-publishing=nevermined_pod_publishing.pod_publishing:main"]
    },
)
