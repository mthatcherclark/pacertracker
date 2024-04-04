import os
from setuptools import setup
from pip.req import parse_requirements

install_reqs = parse_requirements("requirements.txt")
reqs = [str(ir.req) for ir in install_reqs]

README = open(os.path.join(os.path.dirname(__file__), 'README.md')).read()

setup(
    name = "pacertracker",
    version = "1.0",
    packages=['pacertracker'],
    include_package_data=True,
    license = "MIT",
    description = ("A tool to help reporters track federal lawsuits filed in PACER."),
    long_description=README,
    url = "https://github.com/mthatcherclark/pacertracker/",
    author = "Matt Clark",
    author_email = "mattdatajourno@gmail.com",
    keywords = "pacertracker lawsuit pacer track court bankruptcy criminal civil",
    install_requires=reqs,
    classifiers=[
        "Development Status :: 4 - Beta",
        "License :: OSI Approved :: MIT License",
        "Programming Language :: Python :: 3",
        "Topic :: Internet :: WWW/HTTP",
        "Topic :: Internet :: WWW/HTTP :: Dynamic Content",
    ],
)
