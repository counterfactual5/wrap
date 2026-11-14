// Type declaration for the 'project-custom' webpack alias configured in
// remotion.config.ts. The alias resolves to <project>/remotion-custom.tsx
// when the project provides one, otherwise to ./empty. The shape itself lives
// in ./types — this file only binds it to the module name so the engine can
// `import {CUSTOM_COMPONENTS} from 'project-custom'`.
declare module 'project-custom' {
  export type CustomComponentProps = import('./types').CustomComponentProps;
  export type CustomComponentRegistry = import('./types').CustomComponentRegistry;
  export const CUSTOM_COMPONENTS: import('./types').CustomComponentRegistry;
}
