// vision_ocr_ru.swift — локальный OCR кадров через Apple Vision (VNRecognizeText), RU+EN.
// Отличие от ytgs_vision_ocr.swift: явные recognitionLanguages ["ru-RU","en-US"]
// + нормализованные bbox каждой строки (для проверки layout/safe-zone) + без языковой коррекции
// (usesLanguageCorrection = false), чтобы Vision НЕ «чинил» опечатки монтажёра — иначе
// проверка грамматики бессмысленна.
//
// Вход:  пути к изображениям построчно в stdin.
// Выход: по строке JSON на изображение:
//        {"file":..,"w":px,"h":px,"faces":n,"lines":[{"t":текст,"c":conf,"x":..,"y":..,"bw":..,"bh":..}]}
//        Координаты нормализованы 0..1, origin = ЛЕВЫЙ ВЕРХ (y уже перевёрнут из Vision-системы).
//
// Компиляция: swiftc -O vision_ocr_ru.swift -o bin/vision_ocr_ru
// Запуск:     printf '%s\n' /path/a.jpg /path/b.jpg | ./bin/vision_ocr_ru
//             printf '%s\n' /path/a.jpg | ./bin/vision_ocr_ru --langs en-US        (английский канал)
// --langs xx-XX,yy-YY — языки распознавания по порядку приоритета; без аргумента ровно ["ru-RU","en-US"]
// (поведение прежнего бинаря не меняется). Берётся из профиля канала ocr_langs (stages/s2_ocr_hires.py).

import Foundation
import Vision
import AppKit

func parseLangs() -> [String] {
    let args = CommandLine.arguments
    var i = 1
    while i < args.count {
        var value: String? = nil
        if args[i] == "--langs", i + 1 < args.count {
            value = args[i + 1]
            i += 1
        } else if args[i].hasPrefix("--langs=") {
            value = String(args[i].dropFirst("--langs=".count))
        }
        if let v = value {
            let langs = v.split(separator: ",").map { $0.trimmingCharacters(in: .whitespaces) }.filter { !$0.isEmpty }
            if !langs.isEmpty { return langs }
        }
        i += 1
    }
    return ["ru-RU", "en-US"]
}

let recognitionLangs = parseLangs()

func jsonEscape(_ s: String) -> String {
    var o = ""
    for c in s.unicodeScalars {
        switch c {
        case "\"": o += "\\\""
        case "\\": o += "\\\\"
        case "\n": o += "\\n"
        case "\r": o += "\\r"
        case "\t": o += "\\t"
        default:
            if c.value < 0x20 { o += String(format: "\\u%04x", c.value) }
            else { o.unicodeScalars.append(c) }
        }
    }
    return o
}

func analyze(_ path: String) -> String {
    guard let img = NSImage(contentsOfFile: path),
          let cg = img.cgImage(forProposedRect: nil, context: nil, hints: nil) else {
        return "{\"file\":\"\(jsonEscape(path))\",\"error\":\"unreadable\"}"
    }
    let textReq = VNRecognizeTextRequest()
    textReq.recognitionLevel = .accurate
    textReq.usesLanguageCorrection = false
    textReq.recognitionLanguages = recognitionLangs
    let faceReq = VNDetectFaceRectanglesRequest()
    let handler = VNImageRequestHandler(cgImage: cg, options: [:])
    do { try handler.perform([textReq, faceReq]) } catch {
        return "{\"file\":\"\(jsonEscape(path))\",\"error\":\"vision\"}"
    }

    var parts: [String] = []
    if let obs = textReq.results {
        for o in obs {
            guard let top = o.topCandidates(1).first else { continue }
            let b = o.boundingBox                      // Vision: origin = левый НИЗ
            let x = b.origin.x
            let y = 1.0 - b.origin.y - b.size.height   // → левый ВЕРХ
            parts.append("{\"t\":\"\(jsonEscape(top.string))\",\"c\":\(String(format: "%.3f", top.confidence)),\"x\":\(String(format: "%.4f", x)),\"y\":\(String(format: "%.4f", y)),\"bw\":\(String(format: "%.4f", b.size.width)),\"bh\":\(String(format: "%.4f", b.size.height))}")
        }
    }
    let faces = faceReq.results?.count ?? 0
    return "{\"file\":\"\(jsonEscape(path))\",\"w\":\(cg.width),\"h\":\(cg.height),\"faces\":\(faces),\"lines\":[\(parts.joined(separator: ","))]}"
}

while let line = readLine(strippingNewline: true) {
    if line.isEmpty { continue }
    print(analyze(line))
    fflush(stdout)
}
