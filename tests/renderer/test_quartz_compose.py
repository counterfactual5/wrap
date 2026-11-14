"""Regression tests for the native Quartz renderer (macOS only)."""
import pathlib
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[2]
SWIFT = ROOT / "renderers" / "quartz" / "compose.swift"


@unittest.skipUnless(sys.platform == "darwin" and shutil.which("swiftc"), "requires macOS Swift")
class QuartzComposeTests(unittest.TestCase):
    def test_transform_math(self):
        source = SWIFT.read_text().split("// MARK: - Main Renderer")[0]
        checks = r'''
func layer(_ json: String) -> LayerSpec {
    try! JSONDecoder().decode(LayerSpec.self, from: json.data(using: .utf8)!)
}
func near(_ actual: Double, _ expected: Double) {
    precondition(abs(actual - expected) < 1e-8, "\(actual) != \(expected)")
}
let base = layer(#"{"id":"a","type":"ai","rect":[0,0,100,100],"z":0,"depth":0.7}"#)
near(computeLayerTransform(base, 0, 30).depth, 0.7)
let animated = layer(#"{"id":"a","type":"ai","rect":[0,0,100,100],"z":0,"depth":0.7,"anim":{"depth":[[0,1.2]]}}"#)
near(computeLayerTransform(animated, 0, 30).depth, 1)
let flip = layer(#"{"id":"a","type":"ai","rect":[0,0,100,100],"z":0,"pivot":[0,0],"flipX":true,"anim":{"rotate":[[0,90]]}}"#)
let ts = computeLayerTransform(flip, 0, 30)
let pt = transformRodPoint(CGPoint(x: 10, y: 20), ts)
near(Double(pt.x), 20); near(Double(pt.y), 10)
let walk = layer(#"{"id":"leg","type":"ai","rect":[0,0,10,10],"z":0,"gait":{"mode":"walk","freq":1,"phase":0.2}}"#)
let w = computeLayerTransform(walk, 0, 30)
near(w.y, -abs(sin(0.2)) * 6 * 0.35)
near(w.rotate, cos(0.2) * 2.2 * 0.35)
let float = layer(#"{"id":"a","type":"ai","rect":[0,0,10,10],"z":0,"gait":{"mode":"float","phase":0.5}}"#)
let f = computeLayerTransform(float, 0, 30)
near(f.x, cos(0.25) * 2.4); near(f.y, sin(0.5) * 6)
let parent = layer(#"{"id":"parent","type":"ai","rect":[0,0,10,10],"z":0,"gait":{"mode":"shudder"}}"#)
let child = layer(#"{"id":"arm","type":"ai","rect":[0,0,10,10],"z":1}"#)
near(computeLayerTransform(child, 0, 30, parent).rotate, 3.2 * 1.35 * sin(3 * 0.9 * 1.7))
let own = layer(#"{"id":"arm","type":"ai","rect":[0,0,10,10],"z":1,"gait":{"mode":"walk"}}"#)
near(computeLayerTransform(own, 0, 30, parent).rotate, 2.2 * 0.35)
let puppet = layer(#"{"id":"a","type":"ai","rect":[0,0,10,10],"z":0,"gait":{"mode":"puppet","phase":0.6}}"#)
let p = computeLayerTransform(puppet, 0, 30)
let q = Double.pi / 6
near(p.y, -abs(sin(q)) * 6 * 0.35)
near(p.rotate, sin(q) * 2.2 * 0.35 + sin(0.6 * 3.5) * 0.6)
let shudder = layer(#"{"id":"a","type":"ai","rect":[0,0,10,10],"z":0,"gait":{"mode":"shudder","phase":0.5,"range":[0,5]}}"#)
let s = computeLayerTransform(shudder, 0, 30)
near(s.x, sin(0.5 * 2.3) * 6 * 0.65)
near(s.y, cos(0.5 * 1.9) * 6 * 0.45)
near(computeLayerTransform(shudder, 6, 30).y, 0)
let moving = layer(#"{"id":"parent","type":"ai","rect":[0,0,10,10],"z":0,"anim":{"x":[[0,0],[10,100]]}}"#)
near(computeLayerTransform(walk, 5, 30, moving).rotate, cos(2 * Double.pi / 6 + 0.2) * 2.2 * 1.6)
'''
        with tempfile.TemporaryDirectory() as tmp:
            path = pathlib.Path(tmp) / "main.swift"
            binary = pathlib.Path(tmp) / "test"
            path.write_text(source + checks)
            subprocess.run(["swiftc", str(path), "-o", str(binary)], check=True, capture_output=True, text=True)
            subprocess.run([str(binary)], check=True, capture_output=True, text=True)

    def test_renderer_compiles_and_punch_order(self):
        source = SWIFT.read_text()
        self.assertIn("1.0 + 0.13 * sin", source)
        self.assertIn("0.32 * (1.0 - Double(fIdx - pf) / 5.0)", source)
        self.assertLess(source.index("if punchFlash > 0.0"), source.index("for layer in sortedLayers"))
        with tempfile.TemporaryDirectory() as tmp:
            subprocess.run(["swiftc", str(SWIFT), "-o", str(pathlib.Path(tmp) / "renderer")],
                           check=True, capture_output=True, text=True)
