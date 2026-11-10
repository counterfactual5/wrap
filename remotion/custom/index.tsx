// Project-provided custom components. The engine ships none — a project
// registers its own in <project>/remotion-custom.tsx. remotion.config.ts
// aliases the 'project-custom' module to that file when it exists,
// otherwise to ./empty (an empty registry).
export {CUSTOM_COMPONENTS} from 'project-custom';
