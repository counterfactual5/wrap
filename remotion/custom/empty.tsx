import React from 'react';

// Fallback registry used when the project provides no remotion-custom.tsx.
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

export const CUSTOM_COMPONENTS: Record<string, React.FC<CustomComponentProps>> = {};
