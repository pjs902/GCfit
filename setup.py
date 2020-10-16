import io
import os
import setuptools

here = os.path.abspath(os.path.dirname(__file__))

# Package information
NAME = 'GCfit'
VERSION = "0.1.0"

DESCRIPTION = 'Multimass MCMC fitting of Limepy globular cluster analytic model'
with io.open(os.path.join(here, 'README.md'), encoding='utf-8') as f:
    LONG_DESCRIPTION = '\n' + f.read()

# Contributor information
AUTHOR = 'Nolan Dickson'
CONTACT_EMAIL = 'ndickson@ap.smu.ca'

# Installation information
REQUIRED = ['corner', 'h5py', 'emcee', 'ssptools']
REQUIRES_PYTHON = '>=3.7'

# setup parameters
setuptools.setup(
    name=NAME,
    version=VERSION,
    description=DESCRIPTION,
    long_description=LONG_DESCRIPTION,
    long_description_content_type='text/markdown',

    author=AUTHOR,
    author_email=CONTACT_EMAIL,

    install_requires=REQUIRED,
    python_requires=REQUIRES_PYTHON,

    packages=['fitter'],
    # scripts=['bin/pVault'],
    # entry_points={},
)
