export type CachedRenderBundle = {
  etag: string;
  bundle: Record<string, unknown>;
};

const DATABASE = "portlog-render-bundles";
const STORE = "bundles";

function openDatabase(): Promise<IDBDatabase | null> {
  if (typeof indexedDB === "undefined") return Promise.resolve(null);
  return new Promise((resolve, reject) => {
    const request = indexedDB.open(DATABASE, 1);
    request.onupgradeneeded = () => request.result.createObjectStore(STORE);
    request.onsuccess = () => resolve(request.result);
    request.onerror = () => reject(request.error);
  });
}

export function mergeRenderDataWithSession<T extends Record<string, unknown>>(
  session: T,
  bundle: Record<string, unknown>,
): T {
  const renderData = bundle.render_data;
  if (!renderData || typeof renderData !== "object" || Array.isArray(renderData)) return session;
  const render = renderData as Record<string, unknown>;
  return {
    ...session,
    graph: { ...(session.graph as Record<string, unknown>), nodes: render.nodes ?? (session.graph && (session.graph as Record<string, unknown>).nodes), edges: render.edges ?? (session.graph && (session.graph as Record<string, unknown>).edges) },
    pidView: render.pid_view ?? session.pidView,
    schematicScene: render.schematic_scene ?? session.schematicScene,
    schematicSceneKind: render.schematic_scene_kind ?? session.schematicSceneKind,
    geometryReport: render.geometry_report ?? session.geometryReport,
  };
}

export async function readCachedRenderBundle(key: string): Promise<CachedRenderBundle | null> {
  const database = await openDatabase();
  if (!database) return null;
  return new Promise((resolve, reject) => {
    const request = database.transaction(STORE, "readonly").objectStore(STORE).get(key);
    request.onsuccess = () => resolve((request.result as CachedRenderBundle | undefined) ?? null);
    request.onerror = () => reject(request.error);
  });
}

export async function writeCachedRenderBundle(key: string, value: CachedRenderBundle): Promise<void> {
  const database = await openDatabase();
  if (!database) return;
  await new Promise<void>((resolve, reject) => {
    const request = database.transaction(STORE, "readwrite").objectStore(STORE).put(value, key);
    request.onsuccess = () => resolve();
    request.onerror = () => reject(request.error);
  });
}
