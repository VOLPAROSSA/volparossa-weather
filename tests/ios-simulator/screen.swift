// SPDX-License-Identifier: GPL-3.0-only
import ImageIO
import Foundation
import Vision

let url = URL(fileURLWithPath: CommandLine.arguments[1])
let options: [CFString: Any] = [kCGImageSourceCreateThumbnailFromImageAlways: true,
                                kCGImageSourceCreateThumbnailWithTransform: true,
                                kCGImageSourceThumbnailMaxPixelSize: 1600]
guard let source = CGImageSourceCreateWithURL(url as CFURL, nil),
      let image = CGImageSourceCreateThumbnailAtIndex(source, 0, options as CFDictionary) else {
    throw CocoaError(.fileReadCorruptFile)
}
let request = VNRecognizeTextRequest()
request.recognitionLevel = .accurate
request.recognitionLanguages = ["en-US"]
try VNImageRequestHandler(cgImage: image).perform([request])
let words = (request.results ?? []).compactMap { $0.topCandidates(1).first?.string.lowercased() }.joined(separator: " ")
let observation = ["app_title": words.contains("volparossa"),
                   "provider_header": words.contains("current observations") && words.contains("not available"),
                   "native_forecast": words.contains("native weather forecast"),
                   "ifs_model": words.contains("model ifs")]
FileHandle.standardOutput.write(try JSONSerialization.data(withJSONObject: observation, options: [.sortedKeys]))
