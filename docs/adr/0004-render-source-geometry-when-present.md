# Render Source Geometry When Present

Earlier decisions scoped the topology view to an abstract evidence-oriented
graph and explicitly avoided a layout-faithful P&ID renderer. That stance was
adopted when the project believed DEXPI source files carried no usable drawing
geometry, so any faithful-looking rendering would have been an invented
reconstruction and a false fidelity claim.

Inspection of the real-world fixtures (C01 DEXPI reference P&ID, C02 BASF
column, C03 Equinor piping) showed that authoring-tool exports carry full
drawing geometry: equipment positions, piping centerline polylines, and a shape
catalogue. Rendering geometry the file itself provides is grounded source data,
not reconstruction. The pedagogical fixtures (E/I/P series) carry no geometry,
so geometry cannot be required.

The topology review view is therefore tiered: a drawing-faithful schematic view
labeled as drawn when source geometry is present and sane, degrading per element
or per file to an auto-layout schematic view whose connectivity is exactly the
source's while positions are visibly labeled as inferred. The abstract graph
survives only as a debug topology-inspection view. The original concern
survives as a narrower rule: the product never claims its rendering is a
certified substitute for the stamped drawing, and never presents invented
positions as drawn.
