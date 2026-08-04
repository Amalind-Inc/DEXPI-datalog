export type SelectionPersistenceResponse = {
  ok: boolean;
};

export type DocumentSelectionPersistence = {
  activate: () => void;
  restore: () => void;
  request: () => Promise<SelectionPersistenceResponse>;
  isCurrent?: () => boolean;
};

/**
 * Apply an optimistic document selection and restore the previous selection
 * when the durable active-source transition is rejected or unreachable.
 */
export async function persistDocumentSelection({
  activate,
  restore,
  request,
  isCurrent = () => true,
}: DocumentSelectionPersistence): Promise<boolean> {
  activate();
  try {
    const response = await request();
    if (response.ok) return true;
  } catch {
    // A network failure is the same user-visible outcome as a rejected write.
  }
  if (isCurrent()) restore();
  return false;
}
