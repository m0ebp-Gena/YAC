"""Portable Windows entry point; keep writable data beside YAC.exe."""
import sys
from pathlib import Path

import yac


def main():
    root = Path(sys.executable).resolve().parent if getattr(sys, "frozen", False) else Path(__file__).resolve().parent
    yac.project_root = lambda: root
    if '--check-update-connection' in sys.argv:
        import json
        import update_yac
        releases = json.loads(update_yac.fetch(update_yac.API, 2 * 1024 * 1024))
        release = update_yac.newest_release(releases)
        print('Verified GitHub connection from packaged YAC: ' + release['tag_name'])
        return
    if "--check-package" in sys.argv:
        from modules.update_certificates import context
        import ssl
        trust = context()
        assert trust.cert_store_stats()['x509_ca'] > 0
        assert trust.check_hostname and trust.verify_mode == ssl.CERT_REQUIRED
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
        label_names = {path.name for path in (root / 'lang/en/labels').glob('l[0-9][0-9][0-9]')}
        for language in yac.lang_sel.LANGUAGE_CODES:
            language_labels = {path.name for path in (root / 'lang' / language / 'labels').glob('l[0-9][0-9][0-9]')}
            assert language_labels == label_names, (language, 'Label IDs differ')
            for token in label_names:
                assert yac._read_label(root, language, token, ''), (language, token)
            for help_tag in ('h011', 'h012', 'h013', 'h014'):
                assert (root / 'lang' / language / 'help' / help_tag).is_file()
            assert (root / "lang" / language / "labels" / "l000").is_file(), language
            for token in ('l003', 'l025', 'l050', 'l053', 'l129', 'l355', 'l356', 'l367'):
                assert token in label_names, (language, token)
            for help_tag in ('h005', 'h006', 'h007', 'h027', 'h028', 'h029', 'h030', 'h031', 'h032'):
                assert (root / 'lang' / language / 'help' / help_tag).is_file(), (language, help_tag)
        assert any((root / "rad_cmds").rglob("*")), "Missing radio commands"
        from modules.dummy_radio import create_dummy_radio
        radio = create_dummy_radio()
        assert yac.gain_control.adjust(yac, root, radio, "en", "a", 1) == "AF Gain 53%"
        assert yac.gain_control.adjust(yac, root, radio, "en", "r", -1) == "RF Gain 97%"
        power = yac.power_control.prepare(yac, root, radio)
        assert yac.power_control.set_value(yac, radio, power, "33") is None
        assert "Power 33 W" in yac.verify_settings.verify(yac, root, radio, "en")
        assert yac.filter_control.adjust(yac, root, radio, "en") == "Bandwidth 3000 Hz"
        assert yac.filter_control.adjust(yac, root, radio, "en", 1) == "Bandwidth 3200 Hz"
        from modules import noise_blanker
        assert noise_blanker.operate(yac, root, radio, "en", toggle=True) == "NB On"
        assert noise_blanker.operate(yac, root, radio, "en", direction=1) == "NB 6"
        assert noise_blanker.operate(yac, root, radio, "en", toggle=True) == "NB Off"
        from modules import noise_reduction
        assert noise_reduction.operate(yac, root, radio, "en", toggle=True) == "NR On"
        assert noise_reduction.operate(yac, root, radio, "en", direction=1) == "NR Level 6"
        assert noise_reduction.operate(yac, root, radio, "en", toggle=True) == "NR Off"
        from modules import notch_control
        assert notch_control.operate(yac, root, radio, "en", "a", toggle=True) == "Auto Notch On"
        assert notch_control.operate(yac, root, radio, "en", "n", toggle=True) == "Manual Notch On"
        assert notch_control.operate(yac, root, radio, "en", "n", direction=1) == "Notch 1210 Hz"
        assert notch_control.operate(yac, root, radio, "en", "n", width=True) == "Notch Wide"
        from modules import contour_control
        assert contour_control.operate(yac, root, radio, "en", toggle=True) == "Contour On"
        assert contour_control.operate(yac, root, radio, "en", parameter="level", direction=1) == "Dip Level 14"
        assert contour_control.operate(yac, root, radio, "en", parameter="width", direction=-1) == "Width 9"
        assert contour_control.operate(yac, root, radio, "en", direction=1) == "Contour 1210 Hz"
        from modules import filter_verify
        assert filter_verify.verify(yac, root, radio, "en") == "Filters On: Auto Notch On, Manual Notch On, Contour On"
        assert "Filters On:" not in yac.verify_settings.verify(yac, root, radio, "en")
        review = filter_verify.Review()
        assert review.next(yac, root, radio, "en").startswith("Filters On:")
        assert review.next(yac, root, radio, "en") == "NB Off"
        assert review.next(yac, root, radio, "en") == "NR Off"
        assert review.next(yac, root, radio, "en") == "Auto Notch On"
        assert review.next(yac, root, radio, "en") == "Manual Notch On"
        assert review.next(yac, root, radio, "en") == "Contour On"
        assert review.next(yac, root, radio, "en").startswith("Filters On:")
        for language in yac.lang_sel.LANGUAGE_CODES:
            for token in ('l207', 'l208', 'l221', 'l241', 'l001'):
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
        print("Bundled update certificates loaded; hostname and certificate verification enabled.")
        print("Simulated gain, power, bandwidth, noise, notch and Contour controls passed.")
        print("Settings and optional logs stay in: " + str(root))
        print("No radio ports were opened.")
        return
    return yac.main()


if __name__ == "__main__":
    sys.exit(main())
