"""Primitive data structures that constitute the foundation of the BLP model."""

import abc
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple, Union

import numpy as np

from . import options
from .configurations.formulation import ColumnFormulation, Formulation
from .configurations.integration import Integration
from .utilities.basics import Array, Data, Groups, RecArray, extract_matrix, structure_matrices


class Products(object):
    r"""Product data structured as a record array.

    Attributes in addition to the ones below are the variables underlying :math:`X_1`, :math:`X_2`, and :math:`X_3`.

    Attributes
    ----------
    market_ids : `ndarray`
        IDs that associate products with markets.
    firm_ids : `ndarray`
        IDs that associate products with firms.
    demand_ids : `ndarray`
        IDs used to create demand-side fixed effects.
    supply_ids : `ndarray`
        IDs used to create supply-side fixed effects.
    nesting_ids : `ndarray`
        IDs that associate products with nesting groups.
    clustering_ids : `ndarray`
        IDs used to compute clustered standard errors.
    ownership : `ndarray`
        Stacked :math:`J_t \times J_t` ownership matrices, :math:`O`, for each market :math:`t`.
    shares : `ndarray`
        Marketshares, :math:`s`.
    prices : `ndarray`
        Product prices, :math:`p`.
    ZD : `ndarray`
        Full set of demand-side instruments, :math:`Z_D`, which typically consists of excluded demand-side instruments
        and :math:`X_1^\text{ex}`.
    ZS : `ndarray`
        Full set of supply-side instruments, :math:`Z_S`, which typically consists of excluded supply-side instruments
        and :math:`X_3^\text{ex}`.
    X1 : `ndarray`
        Demand-side linear product characteristics, :math:`X_1`.
    X2 : `ndarray`
        Demand-side nonlinear product characteristics, :math:`X_2`.
    X3 : `ndarray`
        Supply-side product characteristics, :math:`X_3`.

    """

    market_ids: Array
    firm_ids: Array
    demand_ids: Array
    supply_ids: Array
    nesting_ids: Array
    ownership: Array
    shares: Array
    ZD: Array
    ZS: Array
    X1: Array
    X2: Array
    X3: Array
    prices: Array

    def __new__(
            cls, product_formulations: Sequence[Optional[Formulation]], product_data: Mapping,
            instruments: bool = True, add_exogenous: bool = True) -> RecArray:
        """Structure product data."""

        # validate the formulations
        if not all(isinstance(f, Formulation) or f is None for f in product_formulations):
            raise TypeError("Each formulation in product_formulations must be a Formulation instance or None.")
        if product_formulations[0] is None:
            raise ValueError("The formulation for X1 must be specified.")
        if product_formulations[1] is not None and product_formulations[1]._absorbed_terms:
            raise ValueError("The formulation for X2 does not support fixed effect absorption.")

        # build X1
        X1, X1_formulations, X1_data = product_formulations[0]._build_matrix(product_data)
        if 'shares' in X1_data:
            raise NameError("shares cannot be included in the formulation for X1.")

        # build X2
        X2 = None
        X2_formulations: List[ColumnFormulation] = []
        X2_data: Data = {}
        if product_formulations[1] is not None:
            X2, X2_formulations, X2_data = product_formulations[1]._build_matrix(product_data)
            if 'shares' in X2_data:
                raise NameError("shares cannot be included in the formulation for X2.")

        # check that prices are in X1 or X2
        if 'prices' not in X1_data and 'prices' not in X2_data:
            raise NameError("prices must be included in at least one of formulations for X1 or X2.")

        # build X3
        X3 = None
        X3_formulations: List[ColumnFormulation] = []
        X3_data: Data = {}
        if product_formulations[2] is not None:
            X3, X3_formulations, X3_data = product_formulations[2]._build_matrix(product_data)
            if 'prices' in X3_data:
                raise NameError("prices cannot be included in the formulation for X3.")

        # load excluded demand-side instruments and supplement them with exogenous characteristics in X1
        ZD = None
        if instruments:
            ZD = extract_matrix(product_data, 'demand_instruments')
            if add_exogenous:
                for index, formulation in enumerate(X1_formulations):
                    if 'prices' not in formulation.names:
                        ZD = X1[:, [index]] if ZD is None else np.c_[ZD, X1[:, [index]]]

        # load excluded supply-side instruments and supplement them with exogenous characteristics in X3
        ZS = None
        if instruments and X3 is not None:
            ZS = extract_matrix(product_data, 'supply_instruments')
            if add_exogenous:
                for index, formulation in enumerate(X3_formulations):
                    if 'shares' not in formulation.names:
                        ZS = X3[:, [index]] if ZS is None else np.c_[ZS, X3[:, [index]]]

        # load fixed effect IDs
        demand_ids = None
        supply_ids = None
        if product_formulations[0]._absorbed_terms:
            demand_ids = product_formulations[0]._build_ids(product_data)
        if product_formulations[2] is not None and product_formulations[2]._absorbed_terms:
            supply_ids = product_formulations[2]._build_ids(product_data)

        # load other IDs
        market_ids = extract_matrix(product_data, 'market_ids')
        firm_ids = extract_matrix(product_data, 'firm_ids')
        nesting_ids = extract_matrix(product_data, 'nesting_ids')
        clustering_ids = extract_matrix(product_data, 'clustering_ids')
        if market_ids is None:
            raise KeyError("product_data must have a market_ids field.")
        if market_ids.shape[1] > 1:
            raise ValueError("The market_ids field of product_data must be one-dimensional.")
        if firm_ids is None and X3 is not None:
            raise KeyError("product_data must have a firm_ids field when X3 is formulated.")
        if firm_ids is not None and firm_ids.shape[1] > 1:
            raise ValueError("The firm_ids field of product_data must be one-dimensional.")
        if nesting_ids is not None and nesting_ids.shape[1] > 1:
            raise ValueError("The nesting_ids field of product_data must be one-dimensional.")
        if clustering_ids is not None:
            if clustering_ids.shape[1] > 1:
                raise ValueError("The clustering_ids field of product_data must be one-dimensional.")
            if np.unique(clustering_ids).size == 1:
                raise ValueError("The clustering_ids field of product_data must have at least two distinct IDs.")

        # load ownership matrices
        ownership = None
        if firm_ids is not None:
            ownership = extract_matrix(product_data, 'ownership')
            if ownership is not None:
                max_J = np.unique(market_ids, return_counts=True)[1].max()
                if ownership.shape[1] != max_J:
                    raise ValueError(
                        f"The ownership field of product_data must have {max_J} columns, which is the number of "
                        f"products in the market with the most products."
                    )

        # load shares
        shares = extract_matrix(product_data, 'shares')
        if shares is None:
            raise KeyError("product_data must have a shares field.")
        if shares.shape[1] > 1:
            raise ValueError("The shares field of product_data must be one-dimensional.")
        if (shares <= 0).any() or (shares >= 1).any():
            raise ValueError("The shares field of product_data must consist of values between zero and one, exclusive.")

        # verify that shares sum to less than one in each market
        market_groups = Groups(market_ids)
        bad_shares_index = market_groups.sum(shares) >= 1
        if np.any(bad_shares_index):
            raise ValueError(
                f"Shares in these markets do not sum to less than 1: {market_groups.unique[bad_shares_index]}"
            )

        # structure product fields as a mapping
        product_mapping: Dict[Union[str, tuple], Tuple[Optional[Array], Any]] = {}
        product_mapping.update({
            'market_ids': (market_ids, np.object),
            'firm_ids': (firm_ids, np.object),
            'demand_ids': (demand_ids, np.object),
            'supply_ids': (supply_ids, np.object),
            'nesting_ids': (nesting_ids, np.object),
            'clustering_ids': (clustering_ids, np.object),
            'ownership': (ownership, options.dtype),
            'shares': (shares, options.dtype),
            'ZD': (ZD, options.dtype),
            'ZS': (ZS, options.dtype)
        })
        product_mapping.update({
            (tuple(X1_formulations), 'X1'): (X1, options.dtype),
            (tuple(X2_formulations), 'X2'): (X2, options.dtype),
            (tuple(X3_formulations), 'X3'): (X3, options.dtype)
        })

        # structure and validate variables underlying X1, X2, and X3
        underlying_data = {k: (v, options.dtype) for k, v in {**X1_data, **X2_data, **X3_data}.items()}
        invalid_names = set(underlying_data) & {k if isinstance(k, str) else k[1] for k in product_mapping}
        if invalid_names:
            raise NameError(f"These reserved names in product_formulations are invalid: {list(invalid_names)}.")

        # structure products
        return structure_matrices({**product_mapping, **underlying_data})


class Agents(object):
    r"""Agent data structured as a record array.

    Attributes
    ----------
    market_ids : `ndarray`
        IDs that associate agents with markets.
    weights : `ndarray`
        Integration weights, :math:`w`.
    nodes : `ndarray`
        Unobserved agent characteristics called integration nodes, :math:`\nu`.
    demographics : `ndarray`
        Observed agent characteristics, :math:`d`.

    """

    market_ids: Array
    weights: Array
    nodes: Array
    demographics: Array

    def __new__(
            cls, products: RecArray, agent_formulation: Optional[Formulation] = None,
            agent_data: Optional[Mapping] = None, integration: Optional[Integration] = None,
            agent_data_name: str = "agent_data", integration_name: str = "integration",
            check_weights: bool = True) -> RecArray:
        """Structure agent data."""

        # data structures may be empty
        market_ids = None
        weights = None
        nodes = None
        demographics = None
        demographics_formulations: List[ColumnFormulation] = []

        # if there are only linear characteristics, build a trivial set of agents
        K2 = products.X2.shape[1]
        if K2 == 0:
            if agent_formulation is not None or agent_data is not None or integration is not None:
                raise ValueError(
                    f"Since X2 is not formulated, none of agent_formulation, {agent_data_name}, and {integration_name} "
                    f"should be specified."
                )
            market_ids = np.unique(products.market_ids)
            weights = np.ones_like(market_ids, options.dtype)
        else:
            # validate the formulation and build demographics
            if agent_formulation is not None:
                if not isinstance(agent_formulation, Formulation):
                    raise TypeError("agent_formulation must be None or a Formulation instance.")
                if agent_data is None:
                    raise ValueError(
                        f"Since agent_formulation is specified, {agent_data_name} must be specified as well."
                    )
                if agent_formulation._absorbed_terms:
                    raise ValueError("agent_formulation does not support fixed effect absorption.")
                demographics, demographics_formulations, _ = agent_formulation._build_matrix(agent_data)

            # load market IDs
            if agent_data is not None:
                market_ids = extract_matrix(agent_data, 'market_ids')
                if market_ids is None:
                    raise KeyError(f"{agent_data_name} must have a market_ids field.")
                if market_ids.shape[1] > 1:
                    raise ValueError(f"The market_ids field of {agent_data_name} must be one-dimensional.")
                if set(np.unique(products.market_ids)) != set(np.unique(market_ids)):
                    raise ValueError(
                        f"The market_ids field of {agent_data_name} must have the same IDs as product data."
                    )

            # build nodes and weights
            if integration is not None:
                if not isinstance(integration, Integration):
                    raise ValueError(f"{integration_name} must be None or an Integration instance.")
                loaded_market_ids = market_ids
                market_ids, nodes, weights = integration._build_many(K2, np.unique(products.market_ids))

                # delete rows of demographics if there are too many
                if demographics is not None:
                    assert loaded_market_ids is not None
                    demographics_list: List[Array] = []
                    for t in np.unique(market_ids):
                        built_rows = (market_ids == t).sum()
                        loaded_rows = (loaded_market_ids == t).sum()
                        if built_rows > loaded_rows:
                            raise ValueError(f"Market '{t}' in {agent_data_name} must have at least {built_rows} rows.")
                        demographics_t = demographics[loaded_market_ids.flat == t]
                        if built_rows < loaded_rows:
                            demographics_t = demographics_t[:built_rows]
                        demographics_list.append(demographics_t)
                    demographics = np.concatenate(demographics_list)

            # load any unbuilt nodes and weights
            if integration is None:
                if agent_data is None:
                    raise ValueError(f"Since {integration_name} is None, {agent_data_name} must be specified.")
                nodes = extract_matrix(agent_data, 'nodes')
                weights = extract_matrix(agent_data, 'weights')
                if nodes is None:
                    raise KeyError(f"Since {integration_name} is None, {agent_data_name} must have nodes.")
                if weights is None:
                    if check_weights:
                        raise KeyError(f"Since {integration_name} is None, {agent_data_name} must have weights.")
                    weights = np.full((nodes.shape[0], 1), np.nan, options.dtype)
                if weights.shape[1] != 1:
                    raise ValueError(f"The weights field of {agent_data_name} must be one-dimensional.")

                # delete columns of nodes if there are too many
                if nodes.shape[1] > K2:
                    nodes = nodes[:, :K2]

        # verify that weights sum to one in each market
        if check_weights:
            market_groups = Groups(market_ids)
            bad_weights_index = np.abs(1 - market_groups.sum(weights)) > options.weights_tol
            if np.any(bad_weights_index):
                raise ValueError(
                    f"Integration weights in these markets sum to a value that differs from 1 by more than "
                    f"options.weights_tol: {market_groups.unique[bad_weights_index]}."
                )

        # structure agents
        return structure_matrices({
            'market_ids': (market_ids, np.object),
            'weights': (weights, options.dtype),
            'nodes': (nodes, options.dtype),
            (tuple(demographics_formulations), 'demographics'): (demographics, options.dtype)
        })


class Container(abc.ABC):
    """An abstract container for structured product and agent data."""

    products: RecArray
    agents: RecArray
    _X1_formulations: Tuple[ColumnFormulation, ...]
    _X2_formulations: Tuple[ColumnFormulation, ...]
    _X3_formulations: Tuple[ColumnFormulation, ...]
    _demographics_formulations: Tuple[ColumnFormulation, ...]

    @abc.abstractmethod
    def __init__(self, products: RecArray, agents: RecArray) -> None:
        """Store data and column formulations."""
        self.products = products
        self.agents = agents
        self._X1_formulations = self.products.dtype.fields['X1'][2]
        self._X2_formulations = self.products.dtype.fields['X2'][2]
        self._X3_formulations = self.products.dtype.fields['X3'][2]
        self._demographics_formulations = self.agents.dtype.fields['demographics'][2]
