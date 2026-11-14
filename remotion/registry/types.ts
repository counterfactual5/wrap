// Shared types for the project-component registry. This is the single
// source of truth: empty.tsx (the engine's fallback registry) and
// project-custom.d.ts (the type declaration for the 'project-custom' webpack
// alias) both reference these definitions instead of duplicating them.
import React from 'react';

export type CustomComponentProps = {
  layer: {
    id: string;
    type: 'component';
    component: string;
    rect: [number, number, number, number];
    z: number;
    props?: Record<string, unknown>;
  };
  rect: [number, number, number, number];
  props?: Record<string, unknown>;
  prepared?: Record<string, string>;
};

export type CustomComponentRegistry = Record<string, React.FC<CustomComponentProps>>;
