import Foundation
import AppKit
import CoreGraphics

// MARK: - JSON Spec Models

struct CanvasSpec: Decodable {
    let w: Int
    let h: Int
    let bg: String?
}

struct PoseSpec: Decodable {
    let frame: Int
    let asset: String
}

struct GaitSpec: Decodable {
    let mode: String
    let freq: Double?
    let bob: Double?
    let sway: Double?
    let phase: Double?
    let range: [Int]?
}

struct MotionSpec: Decodable {
    let type: String?
    let zoom: [Double]?
    let pan: [Double]?
}

struct CaptionItem: Decodable {
    let frame: Int
    let end_frame: Int?
    let text: String
    let hl: String?
    let size: Double?
}

struct LayerParams: Decodable {
    let count: Int?
    let seed: Int?
    let colors: [String]?
    let dir: Double?
    let spread: Double?
    let speed: Double?
    let size: [Double]?
    let glow: Double?
    let d: String?
    let stroke: String?
    let width: Double?
    let reveal: [Double]?
    let hlColor: String?
    let items: [CaptionItem]?
}

struct KeyframeVal: Decodable {
    let frame: Double
    let value: Double
    let ease: String

    init(from decoder: Decoder) throws {
        var container = try decoder.unkeyedContainer()
        self.frame = try container.decode(Double.self)
        self.value = try container.decode(Double.self)
        if !container.isAtEnd {
            self.ease = (try? container.decode(String.self)) ?? "linear"
        } else {
            self.ease = "linear"
        }
    }
}

struct SpringSpec: Decodable {
    let omega: Double?
    let zeta: Double?
    let coupling: Double?
    let channel: String?
    let driverChannel: String?
    let maxAccel: Double?
}

struct AnimSpec: Decodable {
    let x: [KeyframeVal]?
    let y: [KeyframeVal]?
    let scale: [KeyframeVal]?
    let rotate: [KeyframeVal]?
    let opacity: [KeyframeVal]?
    let depth: [KeyframeVal]?
    let flipX: [KeyframeVal]?
}

struct LayerSpec: Decodable {
    let id: String
    let type: String
    let asset: String?
    let draw: String?
    let blend: String?
    let cutout: Bool?
    let plate: Bool?
    let fit: String?
    let parent: String?
    let role: String?
    let shadowColor: String?
    let translucent: Bool?
    let depth: Double?
    let flipX: Bool?
    let controlRod: Bool?
    let rodAnchor: [Double]?
    let rodAnchors: [[Double]]?
    let rect: [Double]
    let clipRect: [Double]?
    let pivot: [Double]?
    let z: Int
    let text: String?
    let subtext: String?
    let fontSize: Double?
    let color: String?
    let poses: [PoseSpec]?
    let motion: MotionSpec?
    let gait: GaitSpec?
    let spring: SpringSpec?
    let anim: AnimSpec?
    let params: LayerParams?
    let title: String?
    let quote: String?
}

struct ShotSpec: Decodable {
    let id: String
    let canvas: CanvasSpec
    let fps: Int
    let durationInFrames: Int
    let punches: [Int]?
    let layers: [LayerSpec]
}

// MARK: - Helpers

func parseHexColor(_ hex: String?, alpha: Double = 1.0) -> NSColor {
    guard let hex = hex else { return NSColor(calibratedRed: 0.0, green: 0.0, blue: 0.0, alpha: CGFloat(alpha)) }
    let clean = hex.trimmingCharacters(in: CharacterSet.alphanumerics.inverted)
    var val: UInt64 = 0
    Scanner(string: clean).scanHexInt64(&val)
    let r = Double((val >> 16) & 0xFF) / 255.0
    let g = Double((val >> 8) & 0xFF) / 255.0
    let b = Double(val & 0xFF) / 255.0
    return NSColor(calibratedRed: CGFloat(r), green: CGFloat(g), blue: CGFloat(b), alpha: CGFloat(alpha))
}

func applyEase(_ t: Double, _ ease: String) -> Double {
    let c = max(0.0, min(1.0, t))
    switch ease {
    case "in":
        return c * c
    case "out":
        return 1.0 - (1.0 - c) * (1.0 - c)
    case "inout":
        return c < 0.5 ? 2.0 * c * c : 1.0 - pow(-2.0 * c + 2.0, 2.0) / 2.0
    case "snap":
        return 1.0 - pow(1.0 - c, 4.0)
    case "overshoot":
        let c1 = 1.70158
        let c3 = c1 + 1.0
        return 1.0 + c3 * pow(c - 1.0, 3.0) + c1 * pow(c - 1.0, 2.0)
    case "step":
        return c < 1.0 ? 0.0 : 1.0
    default:
        return c
    }
}

func channelValue(_ kfs: [KeyframeVal]?, _ frame: Double, _ fallback: Double) -> Double {
    guard let kfs = kfs, !kfs.isEmpty else { return fallback }
    if frame <= kfs.first!.frame { return kfs.first!.value }
    if frame >= kfs.last!.frame { return kfs.last!.value }
    for i in 0..<(kfs.count - 1) {
        let k0 = kfs[i]
        let k1 = kfs[i + 1]
        if frame >= k0.frame && frame <= k1.frame {
            let span = max(1e-6, k1.frame - k0.frame)
            let t = (frame - k0.frame) / span
            return k0.value + (k1.value - k0.value) * applyEase(t, k1.ease)
        }
    }
    return fallback
}

struct TransformState {
    var x: Double
    var y: Double
    var scale: Double
    var rotate: Double
    var opacity: Double
    var depth: Double
    var flipX: Bool
    var pivotX: Double
    var pivotY: Double
}

func selectAnimChannel(_ anim: AnimSpec?, _ name: String) -> [KeyframeVal]? {
    switch name {
    case "x": return anim?.x
    case "y": return anim?.y
    case "scale": return anim?.scale
    case "rotate": return anim?.rotate
    default: return anim?.rotate
    }
}

func computeSpringOffset(_ layer: LayerSpec, _ parentLayer: LayerSpec?, _ frame: Double, _ fps: Double) -> Double {
    guard let sp = layer.spring else { return 0.0 }
    let omega = sp.omega ?? 18.0
    let zeta = sp.zeta ?? 0.25
    let coupling = sp.coupling ?? 0.45
    let maxAccel = max(1.0, sp.maxAccel ?? 4500.0)
    let targetCh = sp.channel ?? "rotate"
    let driverAnim = parentLayer?.anim ?? layer.anim
    let driverKfs: [KeyframeVal]?
    if let dCh = sp.driverChannel {
        driverKfs = selectAnimChannel(driverAnim, dCh)
    } else {
        driverKfs = selectAnimChannel(driverAnim, targetCh) ?? driverAnim?.rotate ?? driverAnim?.x ?? driverAnim?.y ?? driverAnim?.scale
    }
    guard let kfs = driverKfs, kfs.count >= 2 else { return 0.0 }

    let dtFrame = 1.0 / max(1.0, fps)
    let substeps = 4
    let dt = dtFrame / Double(substeps)
    var theta = 0.0
    var vel = 0.0
    let maxF = max(0, Int(frame))
    if maxF >= 1 {
        for f in 1...maxF {
            let fd = Double(f)
            let uPrev = channelValue(kfs, max(0.0, fd - 1.0), 0.0)
            let uCurr = channelValue(kfs, fd, 0.0)
            let uNext = channelValue(kfs, fd + 1.0, uCurr)
            let rawAccel = (uNext - 2.0 * uCurr + uPrev) / (dtFrame * dtFrame)
            let accel = max(-maxAccel, min(maxAccel, rawAccel))
            for _ in 0..<substeps {
                let force = -coupling * accel - 2.0 * zeta * omega * vel - omega * omega * theta
                vel += force * dt
                theta += vel * dt
            }
        }
    }
    return theta
}

func computeLayerTransform(_ layer: LayerSpec, _ frame: Double, _ fps: Double, _ parentLayer: LayerSpec? = nil) -> TransformState {
    let anim = layer.anim
    var x = channelValue(anim?.x, frame, 0.0)
    var y = channelValue(anim?.y, frame, 0.0)
    var scale = channelValue(anim?.scale, frame, 1.0)
    var rotate = channelValue(anim?.rotate, frame, 0.0)
    let opacity = channelValue(anim?.opacity, frame, 1.0)
    let depth = max(0.0, min(1.0, channelValue(anim?.depth, frame, layer.type == "ai" ? (layer.depth ?? 0.0) : 0.0)))

    if let sp = layer.spring {
        let offset = computeSpringOffset(layer, parentLayer, frame, fps)
        let ch = sp.channel ?? "rotate"
        if ch == "x" { x += offset }
        else if ch == "y" { y += offset }
        else if ch == "scale" { scale = max(0.05, scale + offset * 0.01) }
        else { rotate += offset }
    }

    if let gait = layer.gait {
        let inRange = gait.range.map { $0.count != 2 || (frame >= Double($0[0]) && frame <= Double($0[1])) } ?? true
        if inRange {
            let xKeys = (anim?.x?.count ?? 0) >= 2 ? anim?.x : parentLayer?.anim?.x
            let vx = (xKeys?.count ?? 0) >= 2 ? channelValue(xKeys, frame + 1, 0) - channelValue(xKeys, frame - 1, 0) : 0
            let speed = min(1.6, max(0.35, abs(vx) * 0.18))
            let bob = gait.bob ?? 6.0
            let sway = gait.sway ?? 2.2
            let phase = frame / max(1.0, fps) * (gait.freq ?? 3.2) * 2 * Double.pi + (gait.phase ?? 0)
            switch gait.mode {
            case "puppet":
                let qPhase = floor(phase / (2 * Double.pi) * 12 + 0.5) * (2 * Double.pi / 12)
                y -= abs(sin(qPhase)) * bob * speed
                rotate += sin(qPhase) * sway * speed + sin(phase * 3.5) * 0.6
            case "walk":
                y -= abs(sin(phase)) * bob * speed
                rotate += cos(phase) * sway * speed
            case "float":
                x += cos(phase * 0.5) * bob * 0.4
                y += sin(phase) * bob
                rotate += sin(phase * 0.7) * sway
            case "shudder":
                x += sin(phase * 2.3) * bob * 0.65
                y += cos(phase * 1.9) * bob * 0.45
                rotate += sin(phase * 2.7) * sway
            default: break
            }
        }
    } else if let gait = parentLayer?.gait, gait.mode == "shudder" {
        let inRange = gait.range.map { $0.count != 2 || (frame >= Double($0[0]) && frame <= Double($0[1])) } ?? true
        if inRange {
            let phase = frame / max(1.0, fps) * (gait.freq ?? 10) * 2 * Double.pi + Double(layer.id.utf16.count % 5) * 0.9
            rotate += (gait.sway ?? 3.2) * 1.35 * sin(phase * 1.7)
        }
    }

    let baseFlip = (layer.flipX ?? false) ? 1.0 : 0.0
    let fVal = channelValue(anim?.flipX, frame, baseFlip)
    let flipX = fVal >= 0.5

    let px: Double
    let py: Double
    if let piv = layer.pivot, piv.count == 2 {
        px = piv[0]
        py = piv[1]
    } else if layer.type == "text", let titleText = layer.text {
        let fSize = CGFloat(layer.fontSize ?? 54.0)
        let titleFont = NSFont(name: "PingFangSC-Semibold", size: fSize) ?? NSFont.boldSystemFont(ofSize: fSize)
        let nsTitle = NSAttributedString(string: titleText, attributes: [.font: titleFont, .kern: 2.0])
        var contentW = Double(nsTitle.size().width)
        if let sub = layer.subtext, !sub.isEmpty {
            let subFont = NSFont(name: "PingFangSC-Medium", size: max(14.0, fSize * 0.34)) ?? NSFont.systemFont(ofSize: max(14.0, fSize * 0.34))
            let nsSub = NSAttributedString(string: sub, attributes: [.font: subFont, .kern: 1.2])
            contentW = max(contentW, Double(nsSub.size().width))
        }
        px = layer.rect[0] + min(layer.rect[2], max(1.0, contentW)) * 0.5
        py = layer.rect[1] + layer.rect[3] * 0.5
    } else {
        px = layer.rect[0] + layer.rect[2] * 0.5
        py = layer.rect[1] + layer.rect[3] * 0.5
    }

    return TransformState(x: x, y: y, scale: scale, rotate: rotate, opacity: opacity, depth: depth, flipX: flipX, pivotX: px, pivotY: py)
}

func transformRodPoint(_ point: CGPoint, _ ts: TransformState) -> CGPoint {
    let dx = Double(point.x) - ts.pivotX
    let dy = Double(point.y) - ts.pivotY
    let rad = ts.rotate * Double.pi / 180.0
    let ca = cos(rad), sa = sin(rad)
    return CGPoint(
        x: ts.pivotX + ts.x + (ts.flipX ? -ts.scale : ts.scale) * (dx * ca - dy * sa),
        y: ts.pivotY + ts.y + ts.scale * (dx * sa + dy * ca)
    )
}

func pseudoRandom(_ seed: Double) -> Double {
    let x = sin(seed * 9999.0) * 10000.0
    return x - floor(x)
}

// Parse simple SVG path commands ("M x y", "Q cx cy x y", "L x y") in top-left coordinates
func buildCGPath(from d: String) -> CGPath {
    let path = CGMutablePath()
    let tokens = d.replacingOccurrences(of: ",", with: " ")
        .split(whereSeparator: { $0.isWhitespace })
        .map { String($0) }
    var i = 0
    while i < tokens.count {
        let cmd = tokens[i]
        if cmd == "M" && i + 2 < tokens.count {
            if let x = Double(tokens[i + 1]), let y = Double(tokens[i + 2]) {
                path.move(to: CGPoint(x: x, y: y))
            }
            i += 3
        } else if cmd == "L" && i + 2 < tokens.count {
            if let x = Double(tokens[i + 1]), let y = Double(tokens[i + 2]) {
                path.addLine(to: CGPoint(x: x, y: y))
            }
            i += 3
        } else if cmd == "Q" && i + 4 < tokens.count {
            if let cx = Double(tokens[i + 1]), let cy = Double(tokens[i + 2]),
               let x = Double(tokens[i + 3]), let y = Double(tokens[i + 4]) {
                path.addQuadCurve(to: CGPoint(x: x, y: y), control: CGPoint(x: cx, y: cy))
            }
            i += 5
        } else {
            i += 1
        }
    }
    return path
}

// MARK: - Main Renderer

let args = CommandLine.arguments
guard args.count >= 4 else {
    fputs("Usage: quartz_compose <resolved_spec.json> <out_dir> <shot_id>\n", stderr)
    exit(1)
}

let specPath = args[1]
let outDir = args[2]
let shotId = args[3]

let specData = try Data(contentsOf: URL(fileURLWithPath: specPath))
let spec = try JSONDecoder().decode(ShotSpec.self, from: specData)

let W = spec.canvas.w
let H = spec.canvas.h
let FPS = Double(spec.fps)
let totalFrames = spec.durationInFrames
let sortedLayers = spec.layers.sorted { $0.z < $1.z }
var layerMap: [String: LayerSpec] = [:]
for l in spec.layers { layerMap[l.id] = l }

// Preload all prepared PNGs into CGImage cache
var imageCache: [String: CGImage] = [:]
func loadPreparedImage(_ name: String) -> CGImage? {
    if let cached = imageCache[name] { return cached }
    let path = "build/prepared/\(shotId)/\(name).png"
    guard let nsImg = NSImage(contentsOfFile: path),
          let cgImg = nsImg.cgImage(forProposedRect: nil, context: nil, hints: nil) else {
        return nil
    }
    imageCache[name] = cgImg
    return cgImg
}

for l in sortedLayers {
    if l.type == "ai", let asset = l.asset {
        _ = loadPreparedImage("\(l.id)__layer")
        _ = loadPreparedImage(asset)
        if let poses = l.poses {
            for p in poses { _ = loadPreparedImage(p.asset) }
        }
    } else if l.type == "code", let draw = l.draw, (draw == "grid" || draw == "dots") {
        _ = loadPreparedImage(l.id)
    }
}

try FileManager.default.createDirectory(atPath: outDir, withIntermediateDirectories: true)

let colorSpace = CGColorSpace(name: CGColorSpace.sRGB)!
let bitmapInfo = CGImageAlphaInfo.premultipliedLast.rawValue

guard let ctx = CGContext(
    data: nil,
    width: W,
    height: H,
    bitsPerComponent: 8,
    bytesPerRow: W * 4,
    space: colorSpace,
    bitmapInfo: bitmapInfo
) else {
    fputs("Failed to create CGContext\n", stderr)
    exit(1)
}

ctx.interpolationQuality = .high
ctx.setShouldAntialias(true)
ctx.setAllowsAntialiasing(true)

let nsGraphicsContext = NSGraphicsContext(cgContext: ctx, flipped: true)
NSGraphicsContext.current = nsGraphicsContext

for fIdx in 0..<totalFrames {
    autoreleasepool {
        let frame = Double(fIdx)
        ctx.saveGState()

        // Flip coordinate system so (0, 0) is top-left (matching Remotion CSS/SVG coordinates!)
        ctx.translateBy(x: 0, y: CGFloat(H))
        ctx.scaleBy(x: 1.0, y: -1.0)

        // 1. Background fill
        let bgCol = parseHexColor(spec.canvas.bg)
        ctx.setFillColor(bgCol.cgColor)
        ctx.fill(CGRect(x: 0, y: 0, width: W, height: H))

        // 2. Whole-canvas zoom punches & hit flash
        var punchScale = 1.0
        var punchFlash = 0.0
        if let punches = spec.punches {
            for pf in punches {
                if fIdx >= pf && fIdx <= pf + 9 {
                    let s = 1.0 + 0.13 * sin(Double.pi * Double(fIdx - pf) / 9.0)
                    if s > punchScale { punchScale = s }
                }
                if fIdx >= pf && fIdx < pf + 5 {
                    let fl = 0.32 * (1.0 - Double(fIdx - pf) / 5.0)
                    if fl > punchFlash { punchFlash = fl }
                }
            }
        }

        if punchScale != 1.0 {
            let cx = CGFloat(W) * 0.5
            let cy = CGFloat(H) * 0.5
            ctx.translateBy(x: cx, y: cy)
            ctx.scaleBy(x: CGFloat(punchScale), y: CGFloat(punchScale))
            ctx.translateBy(x: -cx, y: -cy)
        }

        // Remotion places the flash behind the layers inside the scaled canvas.
        if punchFlash > 0.0 {
            ctx.setFillColor(NSColor(calibratedWhite: 1.0, alpha: CGFloat(punchFlash)).cgColor)
            ctx.fill(CGRect(x: 0, y: 0, width: W, height: H))
        }

        // 3. Render layers in z-order
        for layer in sortedLayers {
            ctx.saveGState()

            // Clip rect if declared
            if let clip = layer.clipRect, clip.count == 4 {
                ctx.clip(to: CGRect(x: clip[0], y: clip[1], width: clip[2], height: clip[3]))
            }

            // Build ancestor chain [layer, parent, grandparent...]
            var chain: [LayerSpec] = []
            var seen = Set<String>()
            var curr: LayerSpec? = layer
            while let c = curr, !seen.contains(c.id) {
                seen.insert(c.id)
                chain.append(c)
                if let pid = c.parent {
                    curr = layerMap[pid]
                } else {
                    curr = nil
                }
            }

            // Apply transforms from root ancestor down to leaf child
            var combinedOpacity = 1.0
            var combinedDepth = 0.0
            let reversedChain = Array(chain.reversed())
            for idx in 0..<reversedChain.count {
                let item = reversedChain[idx]
                let parentItem = idx > 0 ? reversedChain[idx - 1] : nil
                let ts = computeLayerTransform(item, frame, FPS, parentItem)
                combinedOpacity *= ts.opacity
                combinedDepth = max(combinedDepth, ts.depth)
                if ts.x != 0.0 || ts.y != 0.0 || ts.scale != 1.0 || ts.rotate != 0.0 || ts.flipX {
                    ctx.translateBy(x: CGFloat(ts.pivotX + ts.x), y: CGFloat(ts.pivotY + ts.y))
                    ctx.scaleBy(x: CGFloat(ts.flipX ? -ts.scale : ts.scale), y: CGFloat(ts.scale))
                    ctx.rotate(by: CGFloat(ts.rotate * Double.pi / 180.0))
                    ctx.translateBy(x: CGFloat(-ts.pivotX), y: CGFloat(-ts.pivotY))
                }
            }

            if combinedOpacity <= 0.002 {
                ctx.restoreGState()
                continue
            }
            ctx.setAlpha(CGFloat(combinedOpacity))

            let rx = layer.rect[0]
            let ry = layer.rect[1]
            let rw = layer.rect[2]
            let rh = layer.rect[3]
            let lrect = CGRect(x: rx, y: ry, width: rw, height: rh)

            if layer.type == "ai" || (layer.type == "code" && (layer.draw == "grid" || layer.draw == "dots")) {
                var assetName = layer.type == "ai" ? (layer.asset ?? "") : layer.id
                var hasPoseOverride = false
                if layer.type == "ai", let poses = layer.poses, !poses.isEmpty {
                    for p in poses.reversed() {
                        if fIdx >= p.frame {
                            assetName = p.asset
                            hasPoseOverride = true
                            break
                        }
                    }
                }
                let resolvedImg: CGImage?
                if layer.type == "ai" && !hasPoseOverride, let layerScopedImg = loadPreparedImage("\(layer.id)__layer") {
                    resolvedImg = layerScopedImg
                } else {
                    resolvedImg = loadPreparedImage(assetName)
                }
                if let cgImg = resolvedImg {
                    let z0 = layer.motion?.zoom?.first ?? 1.0
                    let z1 = layer.motion?.zoom?.last ?? 1.0
                    let zScale = z0 + (z1 - z0) * (frame / Double(max(1, totalFrames - 1)))

                    let isCutout = layer.type == "ai" && (layer.cutout ?? false)
                    if !isCutout {
                        ctx.clip(to: lrect)
                    }

                    let imgW = Double(cgImg.width)
                    let imgH = Double(cgImg.height)
                    let fitMode = layer.fit ?? (isCutout ? "contain" : "cover")
                    let fitScale = fitMode == "contain"
                        ? min(rw / max(1.0, imgW), rh / max(1.0, imgH))
                        : max(rw / max(1.0, imgW), rh / max(1.0, imgH))
                    let drawW = imgW * fitScale * zScale
                    let drawH = imgH * fitScale * zScale
                    let drawX = rx + (rw - drawW) * 0.5
                    let drawY = ry + (rh - drawH) * 0.5
                    let drawRect = CGRect(x: drawX, y: drawY, width: drawW, height: drawH)

                    // Draw image in upright orientation inside our top-left flipped context
                    ctx.saveGState()
                    if isCutout {
                        let isTranslucent = layer.translucent ?? (layer.blend == "multiply")
                        let penumbraBlur = 7.0 + combinedDepth * 16.0
                        let penumbraDx = 4.0 + combinedDepth * 8.0
                        let penumbraDy = 6.0 + combinedDepth * 10.0
                        let baseAlpha = isTranslucent ? 0.88 : 1.0
                        let normalAlpha = max(0.1, baseAlpha - combinedDepth * 0.16)
                        let shCol = parseHexColor(layer.shadowColor ?? "#000000", alpha: max(0.05, 0.42 - combinedDepth * 0.12))
                        ctx.setShadow(
                            offset: CGSize(width: penumbraDx, height: penumbraDy),
                            blur: CGFloat(penumbraBlur),
                            color: shCol.cgColor
                        )
                        ctx.setAlpha(CGFloat(combinedOpacity * normalAlpha))
                        ctx.translateBy(x: drawRect.midX, y: drawRect.midY)
                        ctx.scaleBy(x: 1.0, y: -1.0)
                        ctx.draw(cgImg, in: CGRect(x: -drawW * 0.5, y: -drawH * 0.5, width: drawW, height: drawH))
                        ctx.restoreGState()

                        // Optional 2nd pass with .multiply when translucent/multiply mode is enabled
                        if isTranslucent {
                            ctx.saveGState()
                            ctx.setBlendMode(.multiply)
                            ctx.setAlpha(CGFloat(combinedOpacity * 0.28))
                            ctx.translateBy(x: drawRect.midX, y: drawRect.midY)
                            ctx.scaleBy(x: 1.0, y: -1.0)
                            ctx.draw(cgImg, in: CGRect(x: -drawW * 0.5, y: -drawH * 0.5, width: drawW, height: drawH))
                            ctx.restoreGState()
                        }

                        // Multi-point gravity-aligned bamboo/wood support rods (`controlRod: true` + `rodAnchors`):
                        // Every key anatomical node (neck collar, wrists, weapons, props, waist) is propped up
                        // against gravity by a wooden/bamboo support rod extending vertically down to the stage trough.
                        if layer.controlRod ?? false {
                            var anchors: [[Double]] = []
                            if let ras = layer.rodAnchors, !ras.isEmpty {
                                anchors = ras
                            } else if let ra = layer.rodAnchor, ra.count == 2 {
                                anchors = [ra]
                            } else {
                                anchors = [[0.55, 0.46]]
                            }
                            ctx.saveGState()
                            // Undo ancestor+child rotations/scales in reverse order to return to world stage space
                            for idx in 0..<chain.count {
                                let item = chain[idx]
                                let parentItem = idx + 1 < chain.count ? chain[idx + 1] : nil
                                let ts = computeLayerTransform(item, frame, FPS, parentItem)
                                if ts.x != 0.0 || ts.y != 0.0 || ts.scale != 1.0 || ts.rotate != 0.0 || ts.flipX {
                                    ctx.translateBy(x: CGFloat(ts.pivotX), y: CGFloat(ts.pivotY))
                                    ctx.rotate(by: CGFloat(-ts.rotate * Double.pi / 180.0))
                                    let sx = ts.flipX ? -1.0 / max(0.01, ts.scale) : 1.0 / max(0.01, ts.scale)
                                    ctx.scaleBy(x: CGFloat(sx), y: CGFloat(1.0 / max(0.01, ts.scale)))
                                    ctx.translateBy(x: CGFloat(-(ts.pivotX + ts.x)), y: CGFloat(-(ts.pivotY + ts.y)))
                                }
                            }
                            let stageBottomY: Double = (layer.clipRect != nil && layer.clipRect!.count == 4)
                                ? (layer.clipRect![1] + layer.clipRect![3])
                                : Double(H)
                            let coreCol = parseHexColor("#2a1306", alpha: 0.62 * combinedOpacity)
                            let hiCol = parseHexColor("#a8702c", alpha: 0.48 * combinedOpacity)
                            let ringCol = parseHexColor("#c48c32", alpha: 0.78 * combinedOpacity)
                            let pinCol = parseHexColor("#220e03", alpha: 0.85 * combinedOpacity)

                            for (aIdx, anc) in anchors.enumerated() {
                                let ax = anc.first ?? 0.55
                                let ay = anc.last ?? 0.46
                                var wx = rx + rw * ax
                                var wy = ry + rh * ay
                                for idx in 0..<chain.count {
                                    let item = chain[idx]
                                    let parentItem = idx + 1 < chain.count ? chain[idx + 1] : nil
                                    let ts = computeLayerTransform(item, frame, FPS, parentItem)
                                    let point = transformRodPoint(CGPoint(x: wx, y: wy), ts)
                                    wx = Double(point.x)
                                    wy = Double(point.y)
                                }
                                let slant = (layer.parent == nil ? -10.0 : -6.0) + Double(aIdx) * 4.0
                                let handX = wx + slant
                                let handY = max(wy + 40.0, stageBottomY)
                                let rodW: CGFloat = (layer.parent == nil && aIdx == 0) ? 3.8 : 2.8

                                // 1. Dark walnut/bamboo core shaft
                                ctx.setStrokeColor(coreCol.cgColor)
                                ctx.setLineWidth(rodW)
                                ctx.setLineCap(.round)
                                ctx.move(to: CGPoint(x: wx, y: wy))
                                ctx.addLine(to: CGPoint(x: handX, y: handY))
                                ctx.strokePath()

                                // 2. Warm bamboo highlight ridge along shaft
                                ctx.setStrokeColor(hiCol.cgColor)
                                ctx.setLineWidth(1.2)
                                ctx.move(to: CGPoint(x: wx - 0.9, y: wy + 3.0))
                                ctx.addLine(to: CGPoint(x: handX - 0.9, y: handY))
                                ctx.strokePath()

                                // 3. Brass wire hinge collar & dark iron rivet pin at the joint
                                ctx.setFillColor(pinCol.cgColor)
                                ctx.fillEllipse(in: CGRect(x: wx - 2.2, y: wy - 2.2, width: 4.4, height: 4.4))
                                ctx.setStrokeColor(ringCol.cgColor)
                                ctx.setLineWidth(1.6)
                                ctx.strokeEllipse(in: CGRect(x: wx - 4.0, y: wy - 4.0, width: 8.0, height: 8.0))
                            }
                            ctx.restoreGState()
                        }
                    } else {
                        if layer.blend == "multiply" {
                            ctx.setBlendMode(.multiply)
                        } else if layer.blend == "screen" {
                            ctx.setBlendMode(.screen)
                        }
                        ctx.translateBy(x: drawRect.midX, y: drawRect.midY)
                        ctx.scaleBy(x: 1.0, y: -1.0)
                        ctx.draw(cgImg, in: CGRect(x: -drawW * 0.5, y: -drawH * 0.5, width: drawW, height: drawH))
                        ctx.restoreGState()
                    }
                }
            } else if layer.type == "code" {
                let drawType = layer.draw ?? "bar"
                if drawType == "field" {
                    let count = layer.params?.count ?? 32
                    let seed = Double(layer.params?.seed ?? 19)
                    let colors = layer.params?.colors ?? ["#FFD700", "#FF5500"]
                    let speed = layer.params?.speed ?? 1.5
                    let sMin = layer.params?.size?.first ?? 2.0
                    let sMax = layer.params?.size?.last ?? 6.0
                    let glow = layer.params?.glow ?? 12.0

                    for i in 0..<count {
                        let sd = seed + Double(i) * 17.3
                        let px0 = rx + pseudoRandom(sd + 1.0) * rw
                        let py0 = ry + pseudoRandom(sd + 2.0) * rh
                        let pSpeed = (0.5 + pseudoRandom(sd + 3.0)) * speed
                        let px = rx + (px0 - rx + sin(frame * 0.05 + Double(i)) * 28.0 + frame * pSpeed * 0.8).truncatingRemainder(dividingBy: max(1.0, rw))
                        let rawPy = py0 - frame * pSpeed * 1.4
                        let py = ry + ((rawPy - ry).truncatingRemainder(dividingBy: max(1.0, rh)) + rh).truncatingRemainder(dividingBy: max(1.0, rh))
                        let rad = sMin + pseudoRandom(sd + 4.0) * max(1.0, sMax - sMin)
                        let colHex = colors[i % colors.count]
                        let alpha = 0.25 + 0.55 * abs(sin(frame * 0.07 + Double(i)))
                        let col = parseHexColor(colHex, alpha: alpha * combinedOpacity)

                        ctx.saveGState()
                        ctx.setShadow(offset: .zero, blur: CGFloat(glow), color: col.cgColor)
                        ctx.setFillColor(col.cgColor)
                        ctx.fillEllipse(in: CGRect(x: px - rad, y: py - rad, width: rad * 2.0, height: rad * 2.0))
                        ctx.restoreGState()
                    }
                } else if drawType == "path" {
                    if let d = layer.params?.d {
                        var revProgress = 1.0
                        if let rev = layer.params?.reveal, rev.count == 2 {
                            let r0 = rev[0]
                            let r1 = max(r0 + 1.0, rev[1])
                            if frame < r0 {
                                revProgress = 0.0
                            } else if frame <= r1 {
                                revProgress = (frame - r0) / (r1 - r0)
                            }
                        }
                        if revProgress > 0.005 {
                            let strokeCol = parseHexColor(layer.params?.stroke ?? "#FFD700", alpha: combinedOpacity * 0.72)
                            let coreCol = parseHexColor("#FFF6D6", alpha: combinedOpacity * 0.55)
                            let lineW = layer.params?.width ?? 4.0
                            let glow = layer.params?.glow ?? 18.0
                            let cgPath = buildCGPath(from: d)
                            let dashLen = CGFloat(revProgress * 2600.0)

                            ctx.saveGState()
                            ctx.setShadow(offset: .zero, blur: CGFloat(glow), color: strokeCol.cgColor)
                            ctx.setStrokeColor(strokeCol.cgColor)
                            ctx.setLineWidth(CGFloat(lineW))
                            ctx.setLineCap(.round)
                            ctx.setLineJoin(.round)
                            if revProgress < 0.999 {
                                ctx.setLineDash(phase: 0, lengths: [dashLen, 2600.0])
                            }
                            ctx.addPath(cgPath)
                            ctx.strokePath()

                            ctx.setShadow(offset: .zero, blur: CGFloat(glow * 0.35), color: coreCol.cgColor)
                            ctx.setStrokeColor(coreCol.cgColor)
                            ctx.setLineWidth(CGFloat(max(1.2, lineW * 0.38)))
                            ctx.addPath(cgPath)
                            ctx.strokePath()
                            ctx.restoreGState()
                        }
                    }
                } else if drawType == "captions" {
                    if let items = layer.params?.items, !items.isEmpty {
                        var activeItem: CaptionItem? = nil
                        for it in items {
                            if fIdx >= it.frame { activeItem = it }
                        }
                        if let item = activeItem, (item.end_frame == nil || fIdx <= item.end_frame!) {
                            let fSize = CGFloat(item.size ?? 36.0)
                            let font = NSFont(name: "PingFangSC-Semibold", size: fSize) ?? NSFont.boldSystemFont(ofSize: fSize)
                            let hlHex = layer.params?.hlColor ?? "#FFD54F"
                            let hlCol = parseHexColor(hlHex)
                            let whiteCol = NSColor.white

                            let shadow = NSShadow()
                            shadow.shadowColor = NSColor(calibratedRed: 0, green: 0, blue: 0, alpha: 0.92)
                            shadow.shadowOffset = NSSize(width: 0, height: -2)
                            shadow.shadowBlurRadius = 6

                            let baseAttrs: [NSAttributedString.Key: Any] = [
                                .font: font,
                                .foregroundColor: whiteCol,
                                .shadow: shadow,
                                .kern: 1.5
                            ]
                            let attrStr = NSMutableAttributedString(string: item.text, attributes: baseAttrs)
                            if let hl = item.hl, !hl.isEmpty {
                                let nsText = item.text as NSString
                                let range = nsText.range(of: hl)
                                if range.location != NSNotFound {
                                    attrStr.addAttributes([
                                        .foregroundColor: hlCol
                                    ], range: range)
                                }
                            }

                            let textSize = attrStr.size()
                            let padX: CGFloat = 34.0
                            let padY: CGFloat = 10.0
                            let boxW = textSize.width + padX * 2.0
                            let boxH = textSize.height + padY * 2.0
                            let boxX = CGFloat(rx + (rw - Double(boxW)) * 0.5)
                            let boxY = CGFloat(ry + (rh - Double(boxH)) * 0.5)
                            let pillRect = CGRect(x: boxX, y: boxY, width: boxW, height: boxH)

                            // Opera subtitle backing pill
                            let pillPath = CGPath(roundedRect: pillRect, cornerWidth: 8, cornerHeight: 8, transform: nil)
                            ctx.saveGState()
                            ctx.setFillColor(NSColor(calibratedRed: 0.07, green: 0.03, blue: 0.01, alpha: 0.82).cgColor)
                            ctx.addPath(pillPath)
                            ctx.fillPath()
                            ctx.setStrokeColor(NSColor(calibratedRed: 0.83, green: 0.68, blue: 0.22, alpha: 0.45).cgColor)
                            ctx.setLineWidth(1.5)
                            ctx.addPath(pillPath)
                            ctx.strokePath()
                            ctx.restoreGState()

                            attrStr.draw(at: NSPoint(x: boxX + padX, y: boxY + padY))
                        }
                    }
                } else if drawType == "bar" {
                    let col = parseHexColor(layer.color ?? "#E03A3A", alpha: combinedOpacity)
                    let p0 = layer.motion?.pan?.first ?? rx
                    let p1 = layer.motion?.pan?.last ?? rx
                    let curX = p0 + (p1 - p0) * (frame / Double(max(1, totalFrames - 1)))
                    ctx.setFillColor(col.cgColor)
                    ctx.fill(CGRect(x: curX, y: ry, width: rw, height: rh))
                } else {
                    // Fallback / scientific hero draws for test suite compatibility
                    let col = parseHexColor(layer.color ?? "#00F0FF", alpha: combinedOpacity)
                    let p0 = layer.motion?.pan?.first ?? rx
                    let p1 = layer.motion?.pan?.last ?? rx
                    let curX = p0 + (p1 - p0) * (frame / Double(max(1, totalFrames - 1)))
                    ctx.setFillColor(col.cgColor)
                    ctx.fill(CGRect(x: curX, y: ry + sin(frame * 0.15) * 12.0, width: max(24.0, rw * 0.5), height: max(24.0, rh * 0.3)))
                }
            } else if layer.type == "video" {
                let vFramePath = String(format: "build/prepared/%@/_video_frames_%@/%05d.png", shotId, layer.id, fIdx + 1)
                if let nsImg = NSImage(contentsOfFile: vFramePath),
                   let cgImg = nsImg.cgImage(forProposedRect: nil, context: nil, hints: nil) {
                    let z0 = layer.motion?.zoom?.first ?? 1.0
                    let z1 = layer.motion?.zoom?.last ?? 1.0
                    let zScale = z0 + (z1 - z0) * (frame / Double(max(1, totalFrames - 1)))
                    ctx.saveGState()
                    ctx.clip(to: lrect)
                    let imgW = Double(cgImg.width)
                    let imgH = Double(cgImg.height)
                    let fitMode = layer.fit ?? "cover"
                    let fitScale = fitMode == "contain"
                        ? min(rw / max(1.0, imgW), rh / max(1.0, imgH))
                        : max(rw / max(1.0, imgW), rh / max(1.0, imgH))
                    let drawW = imgW * fitScale * zScale
                    let drawH = imgH * fitScale * zScale
                    let drawX = rx + (rw - drawW) * 0.5
                    let drawY = ry + (rh - drawH) * 0.5
                    ctx.translateBy(x: CGFloat(drawX + drawW * 0.5), y: CGFloat(drawY + drawH * 0.5))
                    ctx.scaleBy(x: 1.0, y: -1.0)
                    ctx.draw(cgImg, in: CGRect(x: -drawW * 0.5, y: -drawH * 0.5, width: drawW, height: drawH))
                    ctx.restoreGState()
                }
            } else if layer.type == "text" {
                if let titleText = layer.text {
                    let fSize = CGFloat(layer.fontSize ?? 48.0)
                    let titleFont = NSFont(name: "PingFangSC-Semibold", size: fSize) ?? NSFont.boldSystemFont(ofSize: fSize)
                    let titleCol = parseHexColor(layer.color ?? "#FFE082")

                    let shadow = NSShadow()
                    shadow.shadowColor = NSColor(calibratedRed: 0, green: 0, blue: 0, alpha: 0.9)
                    shadow.shadowOffset = NSSize(width: 0, height: -2)
                    shadow.shadowBlurRadius = 8

                    let titleAttrs: [NSAttributedString.Key: Any] = [
                        .font: titleFont,
                        .foregroundColor: titleCol,
                        .shadow: shadow,
                        .kern: 2.0
                    ]
                    let nsTitle = NSAttributedString(string: titleText, attributes: titleAttrs)
                    nsTitle.draw(at: NSPoint(x: rx, y: ry))

                    if let sub = layer.subtext, !sub.isEmpty {
                        let subFont = NSFont(name: "PingFangSC-Medium", size: max(14.0, fSize * 0.34)) ?? NSFont.systemFont(ofSize: max(14.0, fSize * 0.34))
                        let subAttrs: [NSAttributedString.Key: Any] = [
                            .font: subFont,
                            .foregroundColor: NSColor(calibratedRed: 0.90, green: 0.78, blue: 0.52, alpha: 0.88),
                            .shadow: shadow,
                            .kern: 1.2
                        ]
                        let nsSub = NSAttributedString(string: sub, attributes: subAttrs)
                        nsSub.draw(at: NSPoint(x: rx + 2, y: ry + Double(fSize) + 10.0))
                    }
                }
            } else if layer.type == "card" || layer.type == "hud" || layer.type == "component" {
                let col = parseHexColor(layer.color ?? "#FFD54F", alpha: 0.85 * combinedOpacity)
                ctx.setFillColor(col.cgColor)
                ctx.fill(CGRect(x: rx, y: ry, width: min(rw, 300), height: min(rh, 120)))
            }

            ctx.restoreGState()
        }


        ctx.restoreGState()

        // Write 1-indexed %05d.png
        if let cgImage = ctx.makeImage() {
            let rep = NSBitmapImageRep(cgImage: cgImage)
            if let pngData = rep.representation(using: .png, properties: [:]) {
                let outFile = String(format: "%@/%05d.png", outDir, fIdx + 1)
                try? pngData.write(to: URL(fileURLWithPath: outFile))
            }
        }
    }
}
