// SPDX-License-Identifier: GPL-3.0-only
import Darwin
import Foundation
import XCTest

private enum WitnessError: Error { case transport, deadline(String), screen(String) }

// The witness coordinates only phase names and reads the expected forecast value.
// Application traffic uses an independent, two-route HTTP relay on port 43210.
private func control(_ command: String) throws -> String {
    let fd = socket(AF_INET, SOCK_STREAM, 0)
    guard fd >= 0 else { throw WitnessError.transport }
    defer { close(fd) }
    var timeout = timeval(tv_sec: 120, tv_usec: 0)
    setsockopt(fd, SOL_SOCKET, SO_RCVTIMEO, &timeout, socklen_t(MemoryLayout.size(ofValue: timeout)))
    var address = sockaddr_in()
    address.sin_len = UInt8(MemoryLayout<sockaddr_in>.size)
    address.sin_family = sa_family_t(AF_INET)
    address.sin_port = UInt16(43211).bigEndian
    address.sin_addr = in_addr(s_addr: inet_addr("127.0.0.1"))
    let connected = withUnsafePointer(to: &address) {
        $0.withMemoryRebound(to: sockaddr.self, capacity: 1) { connect(fd, $0, socklen_t(MemoryLayout<sockaddr_in>.size)) }
    }
    guard connected == 0 else { throw WitnessError.transport }
    let data = Data((command + "\n").utf8)
    guard data.withUnsafeBytes({ write(fd, $0.baseAddress, $0.count) }) == data.count else { throw WitnessError.transport }
    var bytes = [UInt8](repeating: 0, count: 256)
    let count = read(fd, &bytes, bytes.count)
    guard count > 0, let reply = String(bytes: bytes.prefix(count), encoding: .utf8), reply.last == "\n" else {
        throw WitnessError.transport
    }
    return String(reply.dropLast())
}

private func waitFor(_ command: String, seconds: TimeInterval = 450) throws -> String {
    let until = Date().addingTimeInterval(seconds)
    repeat {
        let result = try control(command)
        if result != "wait" { return result }
        Thread.sleep(forTimeInterval: 1)
    } while Date() < until
    throw WitnessError.deadline(command)
}

@MainActor
final class WeatherTests: XCTestCase {
    let app = XCUIApplication(bundleIdentifier: "com.marotidev.overmorrow")

    // Match the installed Flutter view through the operating system accessibility tree.
    // Always require an element within the actual device screen before recording a frame.
    private func visible(_ text: String, upward: Bool, steps: Int = 18) throws -> XCUIElement {
        let predicate = NSPredicate(format: "label CONTAINS[c] %@", text)
        let matches = app.descendants(matching: .any).matching(predicate)
        for index in 0...steps {
            for item in matches.allElementsBoundByIndex {
                let frame = item.frame
                if item.elementType != .application && item.elementType != .window &&
                    item.isHittable && !frame.isEmpty && app.frame.contains(CGPoint(x: frame.midX, y: frame.midY)) {
                    return item
                }
            }
            if index != steps {
                let start = app.coordinate(withNormalizedOffset: CGVector(dx: 0.52, dy: upward ? 0.27 : 0.75))
                let end = app.coordinate(withNormalizedOffset: CGVector(dx: 0.52, dy: upward ? 0.78 : 0.27))
                start.press(forDuration: 0.08, thenDragTo: end)
            }
        }
        throw WitnessError.screen(text)
    }

    private func assertRemoved(_ value: String) {
        let predicate = NSPredicate(format: "label CONTAINS[c] %@", value)
        XCTAssertFalse(app.descendants(matching: .any).matching(predicate).firstMatch.exists)
    }

    private func observe(_ phase: String) throws {
        let reply = try control("screen-" + phase)
        XCTAssertEqual(reply, "ok")
    }

    func testSignedForecastLifecycle() throws {
        continueAfterFailure = false
        XCTAssertEqual(try waitFor("start"), "ok")
        XCTAssertEqual(try waitFor("ready-initial", seconds: 1000), "ok")
        app.launch()
        let value = try waitFor("value-initial", seconds: 160)
        _ = try visible(value, upward: false)
        try observe("initial")
        XCTAssertEqual(try waitFor("ready-refused"), "ok")
        _ = try visible("values are hidden", upward: false, steps: 3)
        assertRemoved(value)
        try observe("expired")
        try visible("Refresh forecasts", upward: false).tap()
        XCTAssertEqual(try waitFor("value-refused", seconds: 160), "unavailable")
        _ = try visible("Weather unavailable or expired", upward: true)
        assertRemoved(value)
        try observe("refused")
        XCTAssertEqual(try waitFor("ready-recovered"), "ok")
        try visible("Refresh forecasts", upward: false).tap()
        let replacement = try waitFor("value-recovered", seconds: 160)
        XCTAssertEqual(replacement, value)
        _ = try visible(replacement, upward: true)
        try observe("recovered")
    }
}
