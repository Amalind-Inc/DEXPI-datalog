---
pack_id: demo-process-safety
version: 1
title: Demo process-safety checks
authoritative: false
trust_notice: >-
  Demonstration content only; this pack is not an authoritative code,
  standard, compliance determination, or engineering approval.
---

# Demo process-safety checks

## Pump discharge check valve {#pump_discharge_check_valve}

If a pump has a discharge nozzle, then a check valve must be reachable
downstream on that discharge path before the scope boundary is reached.

```souffle-datalog
// Rule pack: demo-process-safety / pump_discharge_check_valve
//
// Executes over the shared EDB (graph_facts_schema.dl facts) and IDB
// (graph_topology_semantics.dl) layers. Walks downstream from a pump's
// discharge nozzle through Pipe/PipeReducer intermediates and classifies
// the first boundary object reached:
//   matched_required_component -> satisfied (check valve found)
//   off_page_connector         -> indeterminate (scope leaves the page)
//   terminal_object            -> violated (bounded scope, no check valve)
// An ambiguous discharge nozzle or a non-unique next hop yields
// rule_unresolved instead of a boundary.

.decl check_valve_class(label:symbol)
check_valve_class("CheckValve").
check_valve_class("SwingCheckValve").

.decl intermediate_class(label:symbol)
intermediate_class("Pipe").
intermediate_class("PipeReducer").

.decl off_page_class(label:symbol)
off_page_class("FlowOutPipeOffPageConnector").
off_page_class("FlowInPipeOffPageConnector").

.decl pump(id:symbol)
pump(id) :- node_label(id, "CentrifugalPump").

// Nozzles composed on a pump, restricted to those referenced as a
// segment's sourceItem (i.e. the discharge side).
.decl pump_nozzle(pump:symbol, nozzle:symbol)
pump_nozzle(pump, nozzle) :- pump(pump), composition_edge(pump, nozzle, "nozzles").

.decl discharge_candidate(pump:symbol, nozzle:symbol)
discharge_candidate(pump, nozzle) :-
    pump_nozzle(pump, nozzle),
    reference_edge(_, nozzle, "sourceItem").

.decl discharge_candidate_count(pump:symbol, n:number)
discharge_candidate_count(pump, n) :-
    pump(pump),
    n = count : { discharge_candidate(pump, _) }.

.decl discharge_nozzle(pump:symbol, nozzle:symbol)
discharge_nozzle(pump, nozzle) :-
    discharge_candidate(pump, nozzle),
    discharge_candidate_count(pump, 1).

// One traversal hop: a segment references the current object as its
// sourceItem and some object as its targetItem.
.decl next_hop(current:symbol, next:symbol)
next_hop(current, next) :-
    reference_edge(segment, current, "sourceItem"),
    reference_edge(segment, next, "targetItem").

.decl next_hop_count(current:symbol, n:number)
next_hop_count(current, n) :-
    node(current),
    n = count : { next_hop(current, _) }.

.decl unique_next(current:symbol, next:symbol)
unique_next(current, next) :- next_hop(current, next), next_hop_count(current, 1).

.decl node_count(n:number)
node_count(n) :- n = count : { node(_) }.

// Step-indexed deterministic walk from the discharge nozzle. The walk
// extends only through objects allowed to continue (the nozzle itself at
// step 0, then Pipe/PipeReducer intermediates), and is bounded by the
// node count so intermediate cycles cannot recurse forever.
.decl walk(pump:symbol, step:number, object:symbol)
.decl walk_continues(pump:symbol, step:number, object:symbol)

walk(pump, 0, nozzle) :- discharge_nozzle(pump, nozzle).
walk(pump, step + 1, next) :-
    walk_continues(pump, step, object),
    unique_next(object, next),
    node_count(limit),
    step < limit.

walk_continues(pump, 0, nozzle) :- walk(pump, 0, nozzle).
walk_continues(pump, step, object) :-
    walk(pump, step, object),
    step > 0,
    node_label(object, label),
    intermediate_class(label).

// A walk step that should continue but has no unique next hop.
.decl walk_blocked(pump:symbol, step:number, object:symbol)
walk_blocked(pump, step, object) :-
    walk_continues(pump, step, object),
    next_hop_count(object, n),
    n != 1.

// Boundary classification of the first non-continuing object reached.
.decl walk_boundary(pump:symbol, step:number, object:symbol, kind:symbol)
walk_boundary(pump, step, object, "matched_required_component") :-
    walk(pump, step, object),
    step > 0,
    node_label(object, label),
    check_valve_class(label).
walk_boundary(pump, step, object, "off_page_connector") :-
    walk(pump, step, object),
    step > 0,
    node_label(object, label),
    off_page_class(label).
walk_boundary(pump, step, object, "terminal_object") :-
    walk(pump, step, object),
    step > 0,
    node_label(object, label),
    !check_valve_class(label),
    !off_page_class(label),
    !intermediate_class(label).

// The rule cannot establish a bounded scope for this pump.
.decl rule_unresolved(pump:symbol)
rule_unresolved(pump) :- pump(pump), discharge_candidate_count(pump, n), n != 1.
rule_unresolved(pump) :- walk_blocked(pump, _, _).

.output walk
.output walk_boundary
.output rule_unresolved
.output discharge_nozzle
```

## Discharge line minimum nominal diameter {#discharge_line_min_diameter}

The piping line on a pump's discharge side must declare a nominal diameter of
at least DN 25 in the loaded source. The check compares only source-provided
values; if the source carries no numeric diameter for the line, the outcome is
indeterminate (source data unavailable), never an assumed value.

```souffle-datalog
// Rule pack: demo-process-safety / discharge_line_min_diameter
//
// Numeric-threshold demonstration rule over the shared EDB
// (graph_facts_schema.dl facts) and IDB (graph_topology_semantics.dl,
// including the typed node_numeric_attribute predicate).
//
// The pump's discharge line -- the piping segment referencing the pump's
// discharge nozzle as sourceItem, or the PipingNetworkSystem composing that
// segment -- must declare a source-provided nominal diameter of at least
// min_diameter_dn. The threshold compares values already present in the
// DEXPI source; nothing is computed from external formulas or constants.
//   diameter >= threshold -> diameter_satisfied
//   diameter <  threshold -> diameter_violated
//   segment resolved, no numeric diameter anywhere on the line
//                         -> diameter_unavailable (source data unavailable)
// An ambiguous discharge nozzle yields rule_unresolved, as in the
// pump_discharge_check_valve rule.

.decl min_diameter_dn(n:number)
min_diameter_dn(25).

.decl diameter_attr_name(attr_name:symbol)
diameter_attr_name("nominalDiameterNumericalValueRepresentation").

.decl pump(id:symbol)
pump(id) :- node_label(id, "CentrifugalPump").

.decl pump_nozzle(pump:symbol, nozzle:symbol)
pump_nozzle(pump, nozzle) :- pump(pump), composition_edge(pump, nozzle, "nozzles").

.decl discharge_candidate(pump:symbol, nozzle:symbol)
discharge_candidate(pump, nozzle) :-
    pump_nozzle(pump, nozzle),
    reference_edge(_, nozzle, "sourceItem").

.decl discharge_candidate_count(pump:symbol, n:number)
discharge_candidate_count(pump, n) :-
    pump(pump),
    n = count : { discharge_candidate(pump, _) }.

.decl discharge_nozzle(pump:symbol, nozzle:symbol)
discharge_nozzle(pump, nozzle) :-
    discharge_candidate(pump, nozzle),
    discharge_candidate_count(pump, 1).

// The discharge line: the segment referencing the discharge nozzle as its
// sourceItem, plus the piping system that composes that segment.
.decl discharge_segment(pump:symbol, segment:symbol)
discharge_segment(pump, segment) :-
    discharge_nozzle(pump, nozzle),
    reference_edge(segment, nozzle, "sourceItem").

.decl discharge_line_object(pump:symbol, object:symbol)
discharge_line_object(pump, segment) :- discharge_segment(pump, segment).
discharge_line_object(pump, system) :-
    discharge_segment(pump, segment),
    composition_edge(system, segment, "segments").

// Source-provided nominal diameter on any object of the discharge line.
.decl discharge_line_diameter(pump:symbol, object:symbol, dn:number)
discharge_line_diameter(pump, object, dn) :-
    discharge_line_object(pump, object),
    diameter_attr_name(attr),
    node_numeric_attribute(object, attr, dn).

.decl diameter_satisfied(pump:symbol, object:symbol, dn:number)
diameter_satisfied(pump, object, dn) :-
    discharge_line_diameter(pump, object, dn),
    min_diameter_dn(threshold),
    dn >= threshold.

.decl diameter_violated(pump:symbol, object:symbol, dn:number)
diameter_violated(pump, object, dn) :-
    discharge_line_diameter(pump, object, dn),
    min_diameter_dn(threshold),
    dn < threshold.

// The discharge line resolved, but no object on it carries a numeric
// nominal diameter: the source does not provide the data.
.decl diameter_unavailable(pump:symbol)
diameter_unavailable(pump) :-
    discharge_segment(pump, _),
    !discharge_line_diameter(pump, _, _).

.decl rule_unresolved(pump:symbol)
rule_unresolved(pump) :- pump(pump), discharge_candidate_count(pump, n), n != 1.

.output discharge_nozzle
.output discharge_segment
.output discharge_line_diameter
.output diameter_satisfied
.output diameter_violated
.output diameter_unavailable
.output rule_unresolved
```
