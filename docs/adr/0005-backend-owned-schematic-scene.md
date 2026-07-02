# Backend-Owned Schematic Scene

The schematic rendering pipeline is split at a scene boundary: the backend
prepares a renderer-agnostic schematic scene during session preparation, and
the frontend paints it and handles interaction. Symbol resolution order,
inferred pipe routing, the geometry sanity gate, the unplaced-equipment shelf,
and every disclosure recorded in the geometry report are computed in the same
codebase that parses the DEXPI source.

The alternative — shipping raw geometry to the frontend and deriving the
drawing there — was rejected because it re-implements DEXPI geometry semantics
in a second language, splits the trust boundary so the geometry report could
disagree with the render it describes, and removes the renderer from the
deterministic Python test suite. Keeping every fidelity judgment backend-side
continues the existing principle that the application controls deterministic
boundaries while presentation stays thin.

One exception is tolerated: auto-layout position computation for the
auto-layout schematic view may execute client-side if the prototype shows the
best layout engines are JavaScript. Even then, the decision that a scene
requires auto-layout, and its disclosure to the user, remain backend-owned.
