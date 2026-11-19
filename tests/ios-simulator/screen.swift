// SPDX-License-Identifier: GPL-3.0-only
import AppKit
import Foundation
import Vision

let url = URL(fileURLWithPath: CommandLine.arguments[1])
let request = VNRecognizeTextRequest()
request.recognitionLevel = .accurate
request.recognitionLanguages = ["en-US"]
try VNImageRequestHandler(url: url).perform([request])
let words = (request.results ?? []).compactMap { $0.topCandidates(1).first?.string.lowercased() }.joined(separator: " ")
let observation = ["app_title": words.contains("volparossa"),
                   "provider_header": words.contains("current observations") && words.contains("not available"),
                   "native_forecast": words.contains("native weather forecast"),
                   "ifs_model": words.contains("model ifs")]
FileHandle.standardOutput.write(try JSONSerialization.data(withJSONObject: observation, options: [.sortedKeys]))
