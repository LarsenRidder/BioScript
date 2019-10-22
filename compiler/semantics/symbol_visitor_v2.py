import copy

from chemicals.chemtypes import ChemTypes
from chemicals.identifier import Identifier
from compiler.data_structures.properties import FluidProperties, BSVolume
from compiler.data_structures.variable import Movable, Number
from grammar.parsers.python.BSParser import BSParser
from shared.bs_exceptions import *
from .bs_base_visitor import BSBaseVisitor


class SymbolTableVisitorV2(BSBaseVisitor):

    def __init__(self, symbol_table, identifier: Identifier):
        super().__init__(symbol_table, "Symbol Visitor")
        # The identifier to use.
        self.identifier = identifier
        self.rename = False

    def visitProgram(self, ctx: BSParser.ProgramContext):
        # Visiting globals is done in global_visitor.
        # Add main first, it is the root.
        self.symbol_table.new_scope("main")
        self.scope_stack.append('main')

        # We set current_scope equal to main for because the statements
        # hereafter are main's statements.
        self.symbol_table.current_scope = self.symbol_table.scope_map['main']
        for statement in ctx.statements():
            self.visitStatements(statement)

        if ctx.functions():
            self.visitChildren(ctx.functions())

    def visitFunctions(self, ctx: BSParser.FunctionsContext):
        return super().visitFunctions(ctx)

    def visitFunctionDeclaration(self, ctx: BSParser.FunctionDeclarationContext):
        self.scope_stack.append(ctx.IDENTIFIER().__str__())
        self.symbol_table.new_scope(self.scope_stack[-1])
        super().visitFunctionDeclaration(ctx)
        self.scope_stack.pop()
        return None

    def visitFormalParameters(self, ctx: BSParser.FormalParametersContext):
        return super().visitFormalParameters(ctx)

    def visitFormalParameterList(self, ctx: BSParser.FormalParameterListContext):
        return super().visitFormalParameterList(ctx)

    def visitFormalParameter(self, ctx: BSParser.FormalParameterContext):
        return super().visitFormalParameter(ctx)

    def visitFunctionTyping(self, ctx: BSParser.FunctionTypingContext):
        return super().visitFunctionTyping(ctx)

    def visitReturnStatement(self, ctx: BSParser.ReturnStatementContext):
        return super().visitReturnStatement(ctx)

    def visitHeat(self, ctx: BSParser.HeatContext):
        use = self.visitVariable(ctx.variable())
        use_var = self.symbol_table.get_local(use['name'])

        # Get the temperature information.
        heat_to = super().visitTemperatureIdentifier(ctx.temperatureIdentifier())

        # Build the temperature object used to modify the variable
        temp = {'op': 'heat', 'values': {'quantity': heat_to['quantity'], 'units': heat_to['units']}}

        # Modify the variable or its offset.
        if use['index'] == -1:
            for key, value in use_var.value.items():
                value.temperature = temp
        else:
            self.check_bounds(use_var, use['index'])
            use_var.value[use['index']].temperature = temp

        return None

    def visitDispose(self, ctx: BSParser.DisposeContext):
        return super().visitDispose(ctx)

    def visitMix(self, ctx: BSParser.MixContext):
        deff = self.visitVariableDefinition(ctx.variableDefinition())

        uses = list()
        for fluid in ctx.variable():
            temp = self.visitVariable(fluid)
            # This must be get variable, because we don't know if
            # it is a global var or not.
            var = self.symbol_table.get_local(temp['name'])
            self.check_bounds(var, temp['index'])
            uses.append({"var": var, "index": temp['index']})

        # If it is -1 we use the size of the variable, because we are
        # issuing a SIMD instruction.  Otherwise, we just grab the
        # index and run with it.
        use_a = uses[0]['var'].size if uses[0]['index'] == -1 else 1
        use_b = uses[1]['var'].size if uses[1]['index'] == -1 else 1

        # Verify the operation consumes equal amounts of variable(s)
        if use_a != use_b:
            self.log.fatal("Tyring to mix variables of unequal size.")
            raise UnsupportedOperation("Tyring to mix variables of unequal size.")

        # Build the types of this new variable.
        types = set(uses[0]['var'].types)
        types.union(uses[1]['var'].types)

        # We arbitrarily pick a size, because they should be the same.
        variable = Movable(deff['name'], types, self.scope_stack[-1], size=use_a)

        # If this is a SISD instruction, the index of the uses
        # must point to the correct offset.  If there is an offset
        # on the uses, then it's still a SISD instruction, and the index
        # for the deff must be correctly set.
        if uses[0]['index'] == -1 and uses[1]['index'] == -1:
            uses[0]['index'] = 0
            uses[1]['index'] = 0
            deff['index'] = 0
        elif uses[0]['index'] != -1 and uses[1]['index'] != -1:
            deff['index'] = 0

        # These are the intermediate containers for notifying
        # the variable's value property things have changed.
        volumes = {'op': 'mix', 'values': dict()}
        expire_a = {'op': 'use', 'values': dict()}
        expire_b = {'op': 'use', 'values': dict()}
        if use_a == 1:
            # This exists, because the operation could be x[n] = mix a[m] with b[k]
            # And we have to make sure the index of x is maintained through the op.
            # We need to add the volumes of the first and second inputs into one object.
            volumes['values'][deff['index']] = {
                "input_1": {"quantity": uses[0]['var'].value[uses[0]['index']].volume['quantity'],
                            'units': uses[0]['var'].value[uses[0]['index']].volume['units']},
                "input_2": {"quantity": uses[1]['var'].value[uses[1]['index']].volume['quantity'],
                            'units': uses[1]['var'].value[uses[1]['index']].volume['units']}}
            # We need to remove the volume from the first mix input.
            expire_a['values'][uses[0]['index']] = {
                'quantity': uses[0]['var'].value[uses[0]['index']].volume['quantity'],
                'units': uses[0]['var'].value[uses[0]['index']].volume['units']}
            # We need to remove the volume from the second mix input.
            expire_b['values'][uses[1]['index']] = {
                'quantity': uses[1]['var'].value[uses[1]['index']].volume['quantity'],
                'units': uses[1]['var'].value[uses[1]['index']].volume['units']}
        else:
            for x in range(use_a):
                # Add the volumes of the first and second inputs into one object.
                volumes['values'][x] = {"input_1": {"quantity": uses[0]['var'].value[x].volume['quantity'],
                                                    'units': uses[0]['var'].value[x].volume['units']},
                                        "input_2": {"quantity": uses[1]['var'].value[x].volume['quantity'],
                                                    'units': uses[1]['var'].value[x].volume['units']}}
                # Remove the volume from the first mix input.
                expire_a['values'][x] = {'quantity': uses[0]['var'].value[x].volume['quantity'],
                                         'units': uses[0]['var'].value[x].volume['units']}
                # Remove the volume from the second mix input.
                expire_b['values'][x] = {'quantity': uses[1]['var'].value[x].volume['quantity'],
                                         'units': uses[1]['var'].value[x].volume['units']}

        # Set the variable's value property's to reflect the changes.
        variable.value = volumes
        uses[0]['var'].value = expire_a
        uses[1]['var'].value = expire_b

        # Add the new variable to the symbol table.
        self.symbol_table.add_local(variable)
        return None

    def visitDetect(self, ctx: BSParser.DetectContext):
        deff = self.visitVariableDefinition(ctx.variableDefinition())

        # It doesn't matter that we do anything with the module here, we
        # are only collecting symbols. IR is where the module is used
        # mod = self.symbol_table.get_global(ctx.IDENTIFIER().__str__())
        use = self.visitVariable(ctx.variable())
        use_var = self.symbol_table.get_local(use['name'])
        self.check_bounds(use_var, use['index'])

        # Disallow creation of an array on detect if this isn't a SIMD operation.
        if deff['index'] != -1:
            raise UnsupportedOperation("Attempting to create an invalid array.")

        # Validate bounding.
        if use['index'] > use_var.size:
            raise UnsupportedOperation("Attempting to access an invalid offset: sizeof({})={}, attempting to access: {}"
                                       .format(use_var.name, use_var.size, use['index']))

        # The deff_size is 1 if there is an offset on
        # the use, otherwise it is the size of the use_var.
        deff_size = 1 if use['index'] != -1 else use_var.size

        var = Number(deff['name'], scope=self.scope_stack[-1], value=float("nan"), size=deff_size)
        self.symbol_table.add_local(var)

        return None

    def visitSplit(self, ctx: BSParser.SplitContext):
        deff = self.visitVariableDefinition(ctx.variableDefinition())

        use = self.visitVariable(ctx.variable())
        use_var = self.symbol_table.get_local(use['name'])
        self.check_bounds(use_var, use['index'])

        split_num = int(ctx.INTEGER_LITERAL().__str__())

        total_splits = split_num * use_var.size

        var = Movable(deff['name'], use_var.types, self.scope_stack[-1], total_splits)
        offset = 0

        for key, value in use_var.value.items():
            fp = FluidProperties(volume=value.volume['quantity'] / split_num, vol_units=value.volume['units'])
            for x in range(split_num):
                var.value[offset] = copy.deepcopy(fp)
                offset += 1

        self.symbol_table.add_local(var)
        x = 1
        return None

    def visitDispense(self, ctx: BSParser.DispenseContext):
        var = self.visitVariableDefinition(ctx.variableDefinition())

        if not self.symbol_table.get_global(ctx.IDENTIFIER().__str__()):
            self.log.fatal("{} isn't declared in the manifest".format(ctx.IDENTIFIER().__str__()))
            raise UndefinedException("{} isn't declared in the manifest".format(ctx.IDENTIFIER().__str__()))

        # make sure the size is 1 if it's a single variable operation.
        var['index'] = 1 if var['index'] == -1 else var['index']

        variable = Movable(var['name'], self.symbol_table.get_global(ctx.IDENTIFIER().__str__()).types,
                           self.symbol_table.current_scope.name, size=var['index'], volume=10.0)

        self.symbol_table.add_local(variable)

    def visitGradient(self, ctx: BSParser.GradientContext):
        return super().visitGradient(ctx)

    def visitStore(self, ctx: BSParser.StoreContext):
        return super().visitStore(ctx)

    def visitMath(self, ctx: BSParser.MathContext):
        deff = self.visitVariableDefinition(ctx.variableDefinition())
        # this handles array creation.
        deff['index'] = 1 if deff['index'] == -1 else deff['index']

        var = Number(deff['name'], scope=self.scope_stack[-1], size=deff['index'])
        self.symbol_table.add_local(var)

        return None

    def visitBinops(self, ctx: BSParser.BinopsContext):
        return super().visitBinops(ctx)

    def visitParExpression(self, ctx: BSParser.ParExpressionContext):
        return super().visitParExpression(ctx)

    def visitMethodCall(self, ctx: BSParser.MethodCallContext):
        deff = self.visitVariableDefinition(ctx.variableDefinition())
        deff['index'] = 1 if deff['index'] == -1 else deff['index']

        function = self.symbol_table.functions[ctx.IDENTIFIER().__str__()]

        # Update the args for the function.  Because it's impossible
        # To create the variables for the args before hand, it must
        # happen during invocation.
        if ctx.expressionList():
            args = self.visitExpressionList(ctx.expressionList())
            if not function.args and args:
                for arg in args:
                    function.args = arg
                    self.symbol_table.add_local_to_scope(arg['var'], function.name)

        var_types = set()
        if ChemTypes.NAT in function.types or ChemTypes.REAL in function.types:
            var_types.add(ChemTypes.NAT)
            var_types.add(ChemTypes.REAL)
            var = Number(deff['name'], var_types, self.scope_stack[-1], size=deff['index'])
        else:
            var_types.update(function.types)
            size = -1 if not function.size else function.size
            vol = 10.0 if not function.return_var else function.return_var.volume['quantity']
            var = Movable(deff['name'], var_types, self.scope_stack[-1], size=size,
                          volume=vol, units=BSVolume.MICROLITRE)

        self.symbol_table.add_local(var)
        return None

    def visitExpressionList(self, ctx: BSParser.ExpressionListContext):
        args = list()

        for arg in ctx.primary():
            temp = self.visitPrimary(arg)
            var = self.symbol_table.get_local(temp['name'])
            if temp['index'] == -1:
                temp['index'] = var.size
            else:
                self.check_bounds(var, temp['index'])
            temp['index'] = 1 if temp['index'] == -1 else temp['index']
            args.append({'var': var, 'index': temp['index']})

        return args

    def visitTypeType(self, ctx: BSParser.TypeTypeContext):
        return super().visitTypeType(ctx)

    def visitUnionType(self, ctx: BSParser.UnionTypeContext):
        return super().visitUnionType(ctx)

    def visitTypesList(self, ctx: BSParser.TypesListContext):
        return super().visitTypesList(ctx)

    def visitPrimitiveType(self, ctx: BSParser.PrimitiveTypeContext):
        return super().visitPrimitiveType(ctx)

    @staticmethod
    def isPower(x, y):
        """
        Determines if y is a power of x
        :param x: base
        :param y: exponent
        :return: true if input == x^y
        """
        if x == 1:
            return y == 1
        power = 1
        while power < y:
            power = power * x

        return power == y