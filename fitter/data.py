'''observational and modelled data'''

import h5py
import numpy as np
import limepy as lp
from astropy import units as u
from ssptools import evolve_mf_3 as emf3

import logging
from importlib import resources

# TODO better exception handling

# The order of this is important!
DEFAULT_INITIALS = {
    'W0': 6.0,
    'M': 0.69,
    'rh': 2.88,
    'ra': 1.23,
    'g': 0.75,
    'delta': 0.45,
    's2': 0.1,
    'F': 0.45,
    'a1': 0.5,
    'a2': 1.3,
    'a3': 2.5,
    'BHret': 0.5,
    'd': 6.405,
}


# --------------------------------------------------------------------------
# Cluster Observational Data
# --------------------------------------------------------------------------


class Variable(u.Quantity):
    '''simple readonly Quantity subclass to allow metadata on the variable
    '''
    # TODO better way to handle string arrays, and with nicer method failures
    # TODO the "readonly" part of Variable is currently not functional
    def __new__(cls, value, unit=None, mdata=None, *args, **kwargs):

        value = np.asanyarray(value)

        is_str = value.dtype.kind in 'US'

        # If unit is None, look for unit in mdata then assume dimensionless
        if unit is None and mdata is not None:
            try:
                unit = mdata['unit']
            except KeyError:
                pass

        if unit is not None:

            if is_str:
                raise ValueError("value is array of strings, cannot have unit")

            unit = u.Unit(unit)

        # If value is already a quantity, ensure its compatible with given unit
        if isinstance(value, u.Quantity):
            if unit is not None and unit is not value.unit:
                value = value.to(unit)

            unit = value.unit

        # Create the parent object (usually quantity, except if is string)
        if not is_str:
            quant = super().__new__(cls, value, unit, *args, **kwargs)
        else:
            quant = np.asarray(value, *args, **kwargs).view(cls)

        # Store the metadata
        if isinstance(mdata, dict):
            quant.mdata = mdata
        elif mdata is None:
            quant.mdata = dict()
        else:
            raise TypeError('`mdata` must be a dict or None')

        # quant.flags.writeable = False

        return quant

    def __array_finalize__(self, obj):

        if obj is None:
            return

        self.mdata = getattr(obj, 'mdata', dict(defaulted=True))

        try:

            if self._unit is None:
                unit = getattr(obj, '_unit', None)
                if unit is not None:
                    self._set_unit(unit)

            if 'info' in obj.__dict__:
                self.info = obj.info

        except AttributeError:
            pass

        # nump.arra.view is only one now missing its writeable=False
        # if obj.flags.writeable is not False:
        #    self.flags.writeable = False

    def __quantity_subclass__(self, unit):
        return type(self), True


class Dataset:
    '''each group of observations, like mass_function, proper_motions, etc
    init from a h5py group
    not to be confused with h5py datasets, this is more analogous to a group

    h5py attributes are called metadata here cause that is more descriptive
    '''

    def __contains__(self, key):
        return key in self._dict_variables

    def __getitem__(self, key):
        return self._dict_variables[key]

    def _init_variables(self, name, var):
        '''used by group.visit'''

        if isinstance(var, h5py.Dataset):
            mdata = dict(var.attrs)
            self._dict_variables[name] = Variable(var[:], mdata=mdata)

    def __init__(self, group):

        self._dict_variables = {}
        group.visititems(self._init_variables)

        self.mdata = dict(group.attrs)

    @property
    def variables(self):
        return self._dict_variables

    def build_err(self, varname, model_r, model_val):
        '''
        varname is the variable we want to get the error for
        quantity is the actual model data we will be comparing this with

        model_r, _val must be in the right units already (this may be a
        temporary requirement) so do the pc2arcsec conversion beforehand pls
        '''

        try:
            return self[f'Δ{varname}']

        except KeyError:

            try:
                err_up = self[f'Δ{varname},up']
                err_down = self[f'Δ{varname},down']

            except KeyError:
                mssg = f"There are no error(Δ) values associated with {varname}"
                raise ValueError(mssg)

            quantity = self[varname]
            err = np.zeros_like(quantity)

            model_val = np.interp(self['r'], model_r, model_val)

            gt_mask = (model_val > quantity)
            err[gt_mask] = err_up[gt_mask]
            err[~gt_mask] = err_down[~gt_mask]

            return err

    def convert_units(self):
        # TODO auto unit conversions based on attributes
        # This makes me dream about something like astropy units
        pass


class Observations:
    '''Collection of Datasets, read from a corresponding hdf5 file (READONLY)'''

    def __repr__(self):
        return f'Observations(cluster="{self.cluster}")'

    def __str__(self):
        return f'{self.cluster} Observations'

    @property
    def datasets(self):
        return self._dict_datasets

    def __getitem__(self, key):

        try:
            # return a dataset
            return self._dict_datasets[key]
        except KeyError:
            try:
                # return a variable within a dataset
                group, name = key.rsplit('/', maxsplit=1)
                return self._dict_datasets[group][name]

            except ValueError:
                # not in _dict_datasets and no '/' to split on so not a variable
                mssg = f"Dataset '{key}' does not exist"
                raise KeyError(mssg)

            except KeyError:
                # looks like a "dataset/variable" but that variable don't exist
                mssg = f"Dataset or variable '{key}' does not exist"
                raise KeyError(mssg)

    def _find_groups(self, root_group, exclude_initials=True):
        '''lists pathnames to all groups under root_group, excluding initials'''

        def _walker(key, obj):
            if isinstance(obj, h5py.Group):

                if exclude_initials and key == 'initials':
                    return

                # relies on visititems moving top-down
                # this should theoretically remove all parent groups of groups
                try:
                    parent, name = key.rsplit('/', maxsplit=1)
                    groups.remove(parent)

                except ValueError:
                    pass

                groups.append(key)

        groups = []
        root_group.visititems(_walker)

        return groups

    def __init__(self, cluster):

        self.cluster = cluster

        self.mdata = {}
        self._dict_datasets = {}
        self.initials = DEFAULT_INITIALS.copy()

        with resources.path('fitter', 'resources') as datadir:
            with h5py.File(f'{datadir}/{cluster}.hdf5', 'r') as file:

                logging.info(f"Observations read from {datadir}/{cluster}.hdf5")

                for group in self._find_groups(file):
                    self._dict_datasets[group] = Dataset(file[group])

                try:
                    # This updates defaults with data while keeping default sort
                    self.initials = {**self.initials, **file['initials'].attrs}
                except KeyError:
                    logging.info("No initial state stored, using defaults")
                    pass

                # TODO need a way to read units for some mdata from file
                self.mdata = dict(file.attrs)


# --------------------------------------------------------------------------
# Cluster Modelled data
# --------------------------------------------------------------------------

# TODO The units are *very* incomplete in Model (10)

class Model(lp.limepy):

    def __getattr__(self, key):
        '''If `key` is not defined in the limepy model, try to get it from θ'''
        return self._theta[key]

    def _init_mf(self, a12=None, BHret=None):

        m123 = [0.1, 0.5, 1.0, 100]  # Slope breakpoints for imf
        nbin12 = [5, 5, 20]

        if a12 is None:
            a12 = [-self.a1, -self.a2, -self.a3]  # Slopes for imf

        # Output times for the evolution (age)
        tout = np.array([11000])

        # TODO figure out which of these are cluster dependant, store in hdfs

        # Integration settings
        N0 = 5e5  # Normalization of stars
        tcc = 0  # Core collapse time
        NS_ret = 0.1  # Initial neutron star retention
        BH_ret_int = 1  # Initial Black Hole retention
        BH_ret_dyn = self.BHret / 100  # Dynamical Black Hole retention

        # Metallicity
        try:
            FeHe = self.observations.mdata['FeHe']
        except (AttributeError, KeyError):
            logging.warning("No cluster FeHe stored, defaulting to -1.02")
            FeHe = -1.02

        # Regulates low mass objects depletion, default -20, 0 for 47 Tuc
        try:
            Ndot = self.observations.mdata['Ndot']
        except (AttributeError, KeyError):
            logging.warning("No cluster Ndot stored, defaulting to 0")
            Ndot = 0

        # Generate the mass function
        return emf3.evolve_mf(
            m123=m123,
            a12=a12,
            nbin12=nbin12,
            tout=tout,
            N0=N0,
            Ndot=Ndot,
            tcc=tcc,
            NS_ret=NS_ret,
            BH_ret_int=BH_ret_int,
            BH_ret_dyn=BH_ret_dyn,
            FeHe=FeHe,
        )

    # def _get_scale(self):
    #     G_scale, M_scale, R_scale = self._GS, self._MS, self._RS

    def _assign_units(self):
        # TODO this needs to be much more general
        #   Right now it is only applied to those params we use in likelihoods?
        #   Also the actualy units used are being set manually

        # TODO I have no idea how the scaling is supposed to work in limepy

        if not self.scale:
            return

        G_units = u.Unit('(pc km2) / (s2 Msun)')
        R_units = u.pc
        M_units = u.Msun
        V2_units = G_units * M_units / R_units

        self.G *= G_units

        self.M *= M_units
        self.mj *= M_units
        self.mc *= M_units

        self.r *= R_units
        self.rh *= R_units
        self.rt *= R_units
        self.ra *= R_units

        self.v2Tj *= V2_units
        self.v2Rj *= V2_units
        self.v2pj *= V2_units

        # self.Sigmaj *= (M_units / R_units**2)

        self.d *= u.kpc

    def __init__(self, theta, observations=None, *, verbose=False):

        self.observations = observations

        # ------------------------------------------------------------------
        # Unpack theta
        # ------------------------------------------------------------------

        if not isinstance(theta, dict):
            theta = dict(zip(DEFAULT_INITIALS, theta))

        if missing_params := (DEFAULT_INITIALS.keys() - theta.keys()):
            mssg = f"Missing required params: {missing_params}"
            raise KeyError(mssg)

        self._theta = theta

        # ------------------------------------------------------------------
        # Get mass function
        # ------------------------------------------------------------------

        self._mf = self._init_mf((self.a1, self.a2, self.a3), self.BHret)

        # Set bins that should be empty to empty
        cs = self._mf.Ns[-1] > 10 * self._mf.Nmin
        cr = self._mf.Nr[-1] > 10 * self._mf.Nmin

        # Collect mean mass and total mass bins
        mj = np.r_[self._mf.ms[-1][cs], self._mf.mr[-1][cr]]
        Mj = np.r_[self._mf.Ms[-1][cs], self._mf.Mr[-1][cr]]

        # append tracer mass bins (must be appended to end to not affect nms)
        if observations is not None:

            tracer_mj = [
                dataset.mdata['m'] for dataset in observations.datasets.values()
                if 'm' in dataset.mdata
            ]

            mj = np.concatenate((mj, tracer_mj))
            Mj = np.concatenate((Mj, 0.1 * np.ones_like(tracer_mj)))

        else:
            logging.warning("No `Observations` given, no tracer masses added")

        # store some necessary mass function info in the model
        self.nms = len(self._mf.ms[-1][cs])
        self.mes_widths = self._mf.mes[-1][1:] - self._mf.mes[-1][:-1]

        # ------------------------------------------------------------------
        # Create the limepy model base
        # ------------------------------------------------------------------

        super().__init__(
            phi0=self.W0,
            g=self.g,
            M=self.M * 1e6,
            rh=self.rh,
            ra=10**self.ra,
            delta=self.delta,
            mj=mj,
            Mj=Mj,
            project=True,
            verbose=verbose,
        )

        # ------------------------------------------------------------------
        # Assign units
        # ------------------------------------------------------------------

        self._assign_units()
