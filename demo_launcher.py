"""Portable Windows entry point; keep writable data beside YAC.exe."""
import sys
from pathlib import Path

import yac


def main():
    root = Path(sys.executable).resolve().parent if getattr(sys, "frozen", False) else Path(__file__).resolve().parent
    yac.project_root = lambda: root
    if "--check-package" in sys.argv:
        import sounddevice
        from modules.cw_audio import ToneDecoder
        from modules.decoder_text import TextBuffer
        assert sounddevice.get_portaudio_version()[0] > 0
        decoded = TextBuffer()
        decoder = ToneDecoder(decoded)
        decoder.feed([0.0] * 800)
        assert decoded.snapshot() == ''
        assert (root / 'doc/CWKit-LICENSE.txt').is_file()
        import serial
        from serial.tools import list_ports
        assert (root / "yac.ini").is_file(), "Missing yac.ini"
        for language in yac.lang_sel.LANGUAGE_CODES:
            for number in range(247, 295):
                assert yac._read_label(root, language, f'l{number:03d}', ''), (language, number)
            for help_tag in ('h011', 'h012', 'h013', 'h014'):
                assert (root / 'lang' / language / 'help' / help_tag).is_file()
            assert (root / "lang" / language / "labels" / "l000").is_file(), language
            for token in ("l070", "l120", "l140", "l141", "l142", "l143", "l144", "l146",
                          "l065", "l082", "l083", "l147", "l148", "l149", "l150", "l151", "l152",
                          "l153", "l154", "l155", "l156", "l157", "l158", "l159",
                          "l160", "l161", "l162", "l163", "l164", "l165", "l166",
                          "l167", "l168", "l169", "l170"):
                assert yac._read_label(root, language, token, ""), (language, token)
            for help_tag in ("h005", "h006", "h007"):
                assert (root / "lang" / language / "help" / help_tag).is_file(), (language, help_tag)
            for number in range(171, 207):
                assert yac._read_label(root, language, f'l{number:03d}', ''), (language, number)
        assert any((root / "rad_cmds").rglob("*")), "Missing radio commands"
        from modules.dummy_radio import create_dummy_radio
        radio = create_dummy_radio()
        assert yac.gain_control.adjust(yac, root, radio, "en", "a", 1) == "AF Gain 53%"
        assert yac.gain_control.adjust(yac, root, radio, "en", "r", -1) == "RF Gain 97%"
        power = yac.power_control.prepare(yac, root, radio)
        assert yac.power_control.set_value(yac, radio, power, "33") is None
        assert "power 33 watts" in yac.verify_settings.verify(yac, root, radio, "en")
        assert yac.filter_control.adjust(yac, root, radio, "en") == "Bandwidth 3000 Hz"
        assert yac.filter_control.adjust(yac, root, radio, "en", 1) == "Bandwidth 3200 Hz"
        from modules import noise_blanker
        assert noise_blanker.operate(yac, root, radio, "en", toggle=True) == "Noise Blanker On"
        assert noise_blanker.operate(yac, root, radio, "en", direction=1) == "Noise Blanker Level 6"
        assert noise_blanker.operate(yac, root, radio, "en", toggle=True) == "Noise Blanker Off"
        from modules import noise_reduction
        assert noise_reduction.operate(yac, root, radio, "en", toggle=True) == "Noise Reduction On"
        assert noise_reduction.operate(yac, root, radio, "en", direction=1) == "Noise Reduction Level 6"
        assert noise_reduction.operate(yac, root, radio, "en", toggle=True) == "Noise Reduction Off"
        from modules import notch_control
        assert notch_control.operate(yac, root, radio, "en", "a", toggle=True) == "Auto Notch On"
        assert notch_control.operate(yac, root, radio, "en", "n", toggle=True) == "Manual Notch On"
        assert notch_control.operate(yac, root, radio, "en", "n", direction=1) == "Notch Frequency 1210 hertz"
        assert notch_control.operate(yac, root, radio, "en", "n", width=True) == "Notch Width Wide"
        from modules import contour_control
        assert contour_control.operate(yac, root, radio, "en", toggle=True) == "Contour On"
        assert contour_control.operate(yac, root, radio, "en", parameter="level", direction=1) == "Contour level Dip 14"
        assert contour_control.operate(yac, root, radio, "en", parameter="width", direction=-1) == "Contour width 9"
        assert contour_control.operate(yac, root, radio, "en", direction=1) == "Contour frequency 1210 hertz"
        from modules import filter_verify
        assert filter_verify.verify(yac, root, radio, "en") == "Filters On: Auto Notch On, Manual Notch On, Contour On"
        assert "Filters On:" not in yac.verify_settings.verify(yac, root, radio, "en")
        review = filter_verify.Review()
        assert review.next(yac, root, radio, "en").startswith("Filters On:")
        assert review.next(yac, root, radio, "en") == "Noise Blanker Off"
        assert review.next(yac, root, radio, "en") == "Noise Reduction Off"
        assert review.next(yac, root, radio, "en") == "Auto Notch On"
        assert review.next(yac, root, radio, "en") == "Manual Notch On"
        assert review.next(yac, root, radio, "en") == "Contour On"
        assert review.next(yac, root, radio, "en").startswith("Filters On:")
        for language in yac.lang_sel.LANGUAGE_CODES:
            for token in ('l207', 'l208', 'l221', 'l241', 'l246'):
                assert (root / 'lang' / language / 'labels' / token).is_file()
            for help_id in ('h008', 'h009', 'h010'):
                assert (root / 'lang' / language / 'help' / help_id).is_file()
        assert (root / 'doc/supported-radios/ftx-1.txt').is_file()
        from modules import agc_control, mic_gain, speech_processor
        assert agc_control.cycle(yac, root, radio, 'en').startswith('AGC ')
        spec = mic_gain.profile(yac, radio)
        assert mic_gain.adjust(yac, radio, spec, 1) is not None
        spec = speech_processor.profile(yac, radio)
        original = speech_processor.read(yac, radio, spec)
        assert original is not None
        context = speech_processor.context(yac, root, radio)
        assert speech_processor.set_status(yac, radio, spec, True)
        assert speech_processor.restore(yac, root, radio, spec, original, context)
        print("YAC package check passed. Python and pyserial are bundled.")
        print("Simulated gain, power, bandwidth, noise, notch and Contour controls passed.")
        print("Settings and optional logs stay in: " + str(root))
        print("No radio ports were opened.")
        return
    return yac.main()


if __name__ == "__main__":
    sys.exit(main())
