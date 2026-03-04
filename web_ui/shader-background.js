import React from "https://esm.sh/react@18.3.1";
import { createRoot } from "https://esm.sh/react-dom@18.3.1/client";
import { ShaderGradientCanvas, ShaderGradient } from "https://esm.sh/@shadergradient/react@2.4.20?deps=react@18.3.1,react-dom@18.3.1";

const mount = document.getElementById("shader-gradient-root");

if (mount) {
  const root = createRoot(mount);

  root.render(
    React.createElement(
      ShaderGradientCanvas,
      { style: { width: "100%", height: "100%" } },
      React.createElement(ShaderGradient, {
        animate: "on",
        axesHelper: "off",
        brightness: 1,
        cAzimuthAngle: 180,
        cDistance: 3.6,
        cPolarAngle: 90,
        cameraZoom: 1,
        color1: "#00a3ff",
        color2: "#3432c6",
        color3: "#aad9ff",
        destination: "onCanvas",
        embedMode: "off",
        envPreset: "city",
        format: "gif",
        fov: 45,
        frameRate: 10,
        gizmoHelper: "hide",
        grain: "on",
        lightType: "3d",
        pixelDensity: 1,
        positionX: -1.4,
        positionY: 0,
        positionZ: 0,
        range: "enabled",
        rangeEnd: 40,
        rangeStart: 0,
        reflection: 0.1,
        rotationX: 0,
        rotationY: 10,
        rotationZ: 50,
        shader: "defaults",
        type: "plane",
        uAmplitude: 1,
        uDensity: 0.5,
        uFrequency: 5.5,
        uSpeed: 0.2,
        uStrength: 4.1,
        uTime: 0,
        wireframe: false,
      })
    )
  );
}
