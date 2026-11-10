// Type declaration for the 'project-custom' webpack alias configured in
// remotion.config.ts. The alias resolves to <project>/remotion-custom.tsx
// when the project provides one, otherwise to ./empty.
declare module 'project-custom' {
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
  export const CUSTOM_COMPONENTS: Record<string, React.FC<CustomComponentProps>>;
}
