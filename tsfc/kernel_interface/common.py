import collections

import numpy

import coffee.base as coffee

import gem

from gem.utils import cached_property

from tsfc.kernel_interface import KernelInterface


class KernelBuilderBase(KernelInterface):
    """Helper class for building local assembly kernels."""

    def __init__(self, scalar_type, interior_facet=False):
        """Initialise a kernel builder.

        :arg interior_facet: kernel accesses two cells
        """
        assert isinstance(interior_facet, bool)
        self.scalar_type = scalar_type
        self.interior_facet = interior_facet

        self.prepare = []
        self.finalise = []

        # Coordinates
        self.domain_coordinate = {}

        # Coefficients
        self.coefficient_map = {}

    @cached_property
    def unsummed_coefficient_indices(self):
        return frozenset()

    def coordinate(self, domain):
        return self.domain_coordinate[domain]

    def coefficient(self, ufl_coefficient, restriction):
        """A function that maps :class:`ufl.Coefficient`s to GEM
        expressions."""
        kernel_arg = self.coefficient_map[ufl_coefficient]
        if ufl_coefficient.ufl_element().family() == 'Real':
            return kernel_arg
        elif not self.interior_facet:
            return kernel_arg
        else:
            return kernel_arg[{'+': 0, '-': 1}[restriction]]

    def cell_orientation(self, restriction):
        """Cell orientation as a GEM expression."""
        f = {None: 0, '+': 0, '-': 1}[restriction]
        # Assume self._cell_orientations tuple is set up at this point.
        co_int = self._cell_orientations[f]
        return gem.Conditional(gem.Comparison("==", co_int, gem.Literal(1)),
                               gem.Literal(-1),
                               gem.Conditional(gem.Comparison("==", co_int, gem.Zero()),
                                               gem.Literal(1),
                                               gem.Literal(numpy.nan)))

    def cell_size(self, restriction):
        if not hasattr(self, "_cell_sizes"):
            raise RuntimeError("Haven't called set_cell_sizes")
        if self.interior_facet:
            return self._cell_sizes[{'+': 0, '-': 1}[restriction]]
        else:
            return self._cell_sizes

    def entity_number(self, restriction):
        """Facet or vertex number as a GEM index."""
        # Assume self._entity_number dict is set up at this point.
        return self._entity_number[restriction]

    def apply_glue(self, prepare=None, finalise=None):
        """Append glue code for operations that are not handled in the
        GEM abstraction.

        Current uses: mixed interior facet mess

        :arg prepare: code snippets to be prepended to the kernel
        :arg finalise: code snippets to be appended to the kernel
        """
        if prepare is not None:
            self.prepare.extend(prepare)
        if finalise is not None:
            self.finalise.extend(finalise)

    def construct_kernel(self, name, args, body):
        """Construct a COFFEE function declaration with the
        accumulated glue code.

        :arg name: function name
        :arg args: function argument list
        :arg body: function body (:class:`coffee.Block` node)
        :returns: :class:`coffee.FunDecl` object
        """
        assert isinstance(body, coffee.Block)
        body_ = coffee.Block(self.prepare + body.children + self.finalise)
        return coffee.FunDecl("void", name, args, body_, pred=["static", "inline"])

    def register_requirements(self, ir):
        """Inspect what is referenced by the IR that needs to be
        provided by the kernel interface.

        :arg ir: multi-root GEM expression DAG
        """
        # Nothing is required by default
        pass


class KernelBuilderMixin(object):
    """Mixin for KernelBuilder classes."""

    def create_context(self):
        """Create builder context.

        *index_cache*

        Map from UFL FiniteElement objects to multiindices.
        This is so we reuse Index instances when evaluating the same
        coefficient multiple times with the same table.

        We also use the same dict for the unconcatenate index cache,
        which maps index objects to tuples of multiindices. These two
        caches shall never conflict as their keys have different types
        (UFL finite elements vs. GEM index objects).

        *quadrature_indices*

        List of quadrature indices used.

        *mode_irs*

        Dict for mode representations.

        For each set of integrals to make a kernel for (i,e.,
        `integral_data.integrals`), one must first create a ctx object by
        calling :meth:`create_context` method.
        This ctx object collects objects associated with the integrals that
        are eventually used to construct the kernel.
        The following is a typical calling sequence:

        .. code-block:: python3

            builder = KernelBuilder(...)
            params = {"mode": "spectral"}
            ctx = builder.create_context()
            for integral in integral_data.integrals:
                integrand = integral.integrand()
                integrand_exprs = builder.compile_integrand(integrand, params, ctx)
                integral_exprs = builder.construct_integrals(integrand_exprs, params)
                builder.stash_integrals(integral_exprs, params, ctx)
            kernel = builder.construct_kernel(kernel_name, ctx)

        """
        return {'index_cache': {},
                'quadrature_indices': [],
                'mode_irs': collections.OrderedDict()}
