#!/usr/bin/env swift
// generate_dmg_bg.swift — Creates the DMG background image.
// Usage: swift generate_dmg_bg.swift /path/to/output.png
import AppKit

let W: CGFloat = 580
let H: CGFloat = 310

// AppKit origin is bottom-left; Finder positions are top-left.
// Icons at Finder y=130  →  AppKit y = H - 130 = 180
let iconY: CGFloat   = H - 130   // vertical centre of both icons
let appX: CGFloat    = 155        // centre-x of StealthMessage.app
let appsX: CGFloat   = 425        // centre-x of Applications

let img = NSImage(size: NSSize(width: W, height: H))
img.lockFocus()

// ── Background (light) ────────────────────────────────────────────────────────
let bgColor = NSColor(calibratedRed: 0.94, green: 0.94, blue: 0.96, alpha: 1)
bgColor.setFill()
NSRect(origin: .zero, size: NSSize(width: W, height: H)).fill()

// ── Arrow ─────────────────────────────────────────────────────────────────────
// Shaft spans from right edge of app icon to left edge of Applications icon
let shaftX1: CGFloat = appX  + 90   // just past the app icon
let shaftX2: CGFloat = appsX - 90   // just before the Applications icon
let headLen: CGFloat = 26
let headHalf: CGFloat = 16
let shaftY = iconY

// Shaft
let shaft = NSBezierPath()
shaft.lineWidth = 4
shaft.lineCapStyle = .round
shaft.move(to: NSPoint(x: shaftX1, y: shaftY))
shaft.line(to: NSPoint(x: shaftX2 - headLen + 3, y: shaftY))

// Arrowhead (filled triangle)
let head = NSBezierPath()
head.move(to: NSPoint(x: shaftX2,            y: shaftY))
head.line(to: NSPoint(x: shaftX2 - headLen,  y: shaftY + headHalf))
head.line(to: NSPoint(x: shaftX2 - headLen,  y: shaftY - headHalf))
head.close()

NSColor(calibratedWhite: 0.35, alpha: 0.90).setStroke()
NSColor(calibratedWhite: 0.35, alpha: 0.90).setFill()
shaft.stroke()
head.fill()

// ── "Drag to install" label ───────────────────────────────────────────────────
let arrowAttrs: [NSAttributedString.Key: Any] = [
    .font: NSFont.systemFont(ofSize: 13, weight: .medium),
    .foregroundColor: NSColor(calibratedWhite: 0.40, alpha: 1),
]
let arrowLabel = "Drag to install" as NSString
let arrowLabelSize = arrowLabel.size(withAttributes: arrowAttrs)
let arrowLabelX = (shaftX1 + shaftX2) / 2 - arrowLabelSize.width / 2
let arrowLabelY = shaftY - 28
arrowLabel.draw(at: NSPoint(x: arrowLabelX, y: arrowLabelY), withAttributes: arrowAttrs)


img.unlockFocus()

// ── Write PNG ─────────────────────────────────────────────────────────────────
guard
    let tiff = img.tiffRepresentation,
    let rep  = NSBitmapImageRep(data: tiff),
    let png  = rep.representation(using: .png, properties: [:])
else {
    fputs("Error: could not render image\n", stderr)
    exit(1)
}

let out = CommandLine.arguments.count > 1
    ? CommandLine.arguments[1]
    : "/tmp/dmg_background.png"

do {
    try png.write(to: URL(fileURLWithPath: out))
    print("Background written: \(out)")
} catch {
    fputs("Write error: \(error)\n", stderr)
    exit(1)
}
