// Plain values (no "use client") so server components can import the real
// numbers/strings at render time -- a "use client" module's exports are all
// replaced with opaque client references on the server, even simple consts.
export const WIDTH_STORAGE_KEY = "pydexpi.appSidebar.width.v1";
export const DEFAULT_WIDTH = 220;
export const MIN_WIDTH = 180;
export const MAX_WIDTH = 360;
