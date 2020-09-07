import os
from setuptools import setup
from pip.req import parse_requirements

install_reqs = parse_requirements("requirements.txt")
reqs = [str(ir.req) for ir in install_reqs]

README = open(os.path.join(os.path.dirname(__file__), 'README.md')).read()

setup(
    name = "pacertracker",
    version = "0.1",
    packages=['pacertracker'],
    include_package_data=True,
    # license = "MIT", # not yet
    description = ("A tool to help reporters track federal lawsuits filed in PACER"),
    long_description=README,
    url = "http://github.com/newsday/checkup",
    author = "Matt Clark",
    author_email = "mr.matthew.clark@gmail.com",
    keywords = "newstools newsday pacertracker lawsuit pacer track court bankruptcy",
    install_requires=reqs,
    classifiers=[
        "Development Status :: 4 - Beta",
        "License :: OSI Approved :: MIT License",
        "Programming Language :: Python :: 2",
        "Topic :: Internet :: WWW/HTTP",
        "Topic :: Internet :: WWW/HTTP :: Dynamic Content",
    ],
)
