// Project-provided custom-component registry.
//
// A project selects its components with `type: "component"` layers. They are
// looked up by name in CUSTOM_COMPONENTS, a map the engine does not ship —
// the project does. The mechanism:
//   1. `remotion.config.ts` aliases the module 'project-custom' to
//      <project>/remotion-custom.tsx when the project provides one,
//      otherwise to ./empty (an empty registry).
//   2. This file re-exports that registry so the renderer can import it
//      without knowing which one it resolved to.
//   3. Type resolution for the virtual module 'project-custom' comes from
//      project-custom.d.ts.
//
// When no project file exists the registry is empty and component layers
// render as a dashed placeholder box (see Shot.tsx).
export {CUSTOM_COMPONENTS} from 'project-custom';
