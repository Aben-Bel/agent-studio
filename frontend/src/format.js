// Display helpers. Agent/tool ids are snake_case internally (e.g.
// "defect_inspection_agent"); show them to the user as "defect inspection agent".
// Use ONLY for display — never pass the prettified string back as an id.
export const prettyName = (n) => String(n || "").replace(/_/g, " ");
