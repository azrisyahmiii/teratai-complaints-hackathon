"""Malay reply templates (SPEC §4.6), formal register: Tuan/Puan, pihak bank, Sekian, terima kasih ("Dukacita dimaklumkan" only for bad news).

Same keys and placeholders as `en.py`. BA reviews the wording; regulatory contacts are limited to the verified ones
in `check.py` (NSRC 997, FMOS, BNMLINK 1-300-88-5465).
"""

MONTHS = [
    "Januari", "Februari", "Mac", "April", "Mei", "Jun",
    "Julai", "Ogos", "September", "Oktober", "November", "Disember",
]  # fmt: skip

OPEN = "{who},\n\nTerima kasih kerana menghubungi pihak bank. "
CLOSE = "\n\nSekian, terima kasih.\nPihak Teratai Bank"

REDRESS = (
    "Jika anda tidak berpuas hati dengan keputusan ini, anda boleh merujuk perkara ini kepada Financial Markets "
    "Ombudsman Service (FMOS) atau menghubungi BNMLINK di 1-300-88-5465."
)
SCAM_HELP = "Sila hubungi juga National Scam Response Centre (NSRC) di 997 dan, jika dinasihatkan, buat laporan polis."
REFUND_TIME = "dalam masa {sla_days} hari bekerja"

TEXTS: dict[str, str] = {
    "DUPLICATE_CHARGE.REFUND": OPEN
    + "Kami telah menyemak caj kad anda{at} dan mendapati transaksi {txn} sebanyak {amount} pada {date} telah dicaj dua "
    "kali. Jumlah {refund} akan dikreditkan semula ke akaun anda " + REFUND_TIME + "." + CLOSE,
    "DUPLICATE_CHARGE.DECLINE.reversed": OPEN
    + "Kami telah menyemak transaksi kad {txn} sebanyak {amount}{at} pada {date}. Caj berganda tersebut telah "
    "dimasukkan semula ke akaun anda pada {rev_date}, maka tiada bayaran lanjut perlu dibuat. {redress}"
    + CLOSE,
    "DUPLICATE_CHARGE.DECLINE.single": OPEN
    + "Kami telah menyemak transaksi kad {txn} sebanyak {amount}{at} pada {date} tetapi tidak menemui caj yang sama "
    "sebelumnya. Ia nampaknya satu pembelian yang sah, jadi kami tidak dapat memulangkan wang tersebut. {redress}"
    + CLOSE,
    "DUPLICATE_CHARGE.DECLINE.apart": OPEN
    + "Kami telah menyemak transaksi kad {txn} sebanyak {amount}{at} pada {date}. Terdapat caj yang serupa, tetapi "
    "kedua-dua caj itu tidak dibuat dalam tempoh yang cukup dekat untuk dianggap caj berganda, jadi kami tidak dapat "
    "memulangkan wang tersebut. {redress}" + CLOSE,
    "FAILED_TRANSFER.REFUND": OPEN
    + "Kami mengesahkan bahawa pemindahan wang anda{to} sebanyak {amount} pada {date} (transaksi {txn}) telah gagal dan "
    "wang itu belum dikembalikan kepada anda. Jumlah {refund} akan dikreditkan semula ke akaun anda "
    + REFUND_TIME
    + "."
    + CLOSE,
    "FAILED_TRANSFER.DECLINE.reversed": OPEN
    + "Pemindahan wang anda{to} sebanyak {amount} pada {date} (transaksi {txn}) tidak berjaya, dan wang itu telah "
    "dimasukkan semula ke akaun anda pada {rev_date}. Tiada bayaran lanjut perlu dibuat. {redress}" + CLOSE,
    "FAILED_TRANSFER.DECLINE.completed": OPEN
    + "Rekod kami menunjukkan pemindahan wang anda{to} sebanyak {amount} pada {date} (transaksi {txn}) telah berjaya "
    "dan wang itu sampai ke bank penerima, jadi kami tidak dapat memulangkan wang tersebut. {redress}"
    + CLOSE,
    "ATM_NOT_DISPENSED.REFUND": OPEN
    + "Rekod ATM bagi transaksi {txn} pada {date} menunjukkan anda meminta {requested} tetapi hanya {dispensed} "
    "dikeluarkan. Jumlah kekurangan {refund} akan dikreditkan semula ke akaun anda "
    + REFUND_TIME
    + "."
    + CLOSE,
    "ATM_NOT_DISPENSED.DECLINE": OPEN
    + "Rekod ATM bagi transaksi {txn} pada {date} menunjukkan jumlah penuh {requested} telah dikeluarkan, jadi kami "
    "tidak dapat memulangkan wang tersebut. {redress}" + CLOSE,
    "UNAUTHORISED_CARD.REFUND": OPEN
    + "Kami telah menyemak transaksi kad {txn} sebanyak {amount}{at} pada {date}, yang diproses tanpa pengesahan. "
    "Jumlah {refund} akan dikreditkan semula ke akaun anda " + REFUND_TIME + "." + CLOSE,
    "UNAUTHORISED_CARD.INVESTIGATE": OPEN
    + "Kami telah menerima laporan anda mengenai transaksi kad {txn} sebanyak {amount}{at} pada {date}. Pasukan "
    "penipuan kami sedang menyiasat dan akan menghubungi anda dalam masa {sla_days} hari bekerja, kemudian akan memaklumkan perkembangan sekurang-kurangnya setiap "
    "{update_days} hari bekerja. Belum ada keputusan mengenai pemulangan wang. Sila pastikan kad anda selamat dan maklumkan kepada kami dengan segera tentang "
    "sebarang transaksi lain yang anda tidak kenali." + CLOSE,
    "SCAM_TRANSFER.INVESTIGATE": OPEN
    + "Kami memohon maaf atas kesulitan yang anda alami. Pasukan penipuan kami telah mula menyiasat "
    "pemindahan wang anda{to} sebanyak {amount} pada {date} (transaksi {txn}) dan akan cuba menuntut semula dana "
    "tersebut, walaupun pemulihan tidak dijamin. {scam_help} Kami akan memaklumkan perkembangan sekurang-kurangnya "
    "setiap {update_days} hari bekerja sehingga siasatan selesai." + CLOSE,
    "FEE_DISPUTE.REFUND": OPEN
    + "Kami telah menyemak transaksi yuran {txn} sebanyak {charged} pada {date}. Yuran yang sepatutnya dikenakan ialah "
    "{due}. Beza sebanyak {refund} akan dikreditkan semula ke akaun anda " + REFUND_TIME + "." + CLOSE,
    "FEE_DISPUTE.REFUND.waived": OPEN
    + "Kami telah menyemak transaksi yuran {txn} sebanyak {charged} pada {date}. Tiada yuran sepatutnya dikenakan ke "
    "atas akaun anda, maka jumlah {refund} akan dikreditkan semula " + REFUND_TIME + "." + CLOSE,
    "FEE_DISPUTE.DECLINE": OPEN
    + "Kami telah menyemak transaksi yuran {txn} sebanyak {charged} pada {date}. Yuran tersebut adalah mengikut jadual "
    "yuran bagi akaun anda, jadi kami tidak dapat memulangkan wang tersebut. {redress}" + CLOSE,
    "SERVICE_QUALITY.INFO_ONLY": OPEN
    + "Kami memohon maaf atas pengalaman kurang menyenangkan yang anda alami. Aduan anda telah direkodkan dan "
    "dirujuk kepada pasukan berkenaan, yang akan menyemaknya dan memberi maklum balas dalam masa {sla_days} hari "
    "bekerja." + CLOSE,
    "NEEDS_INFO": OPEN
    + "Untuk menyemak aduan anda, kami memerlukan sedikit maklumat tambahan. Sila balas dengan tarikh transaksi, "
    "jumlahnya dan nama pedagang atau penerima. Setelah kami menerima maklumat ini, kami akan menyemak kes anda dalam "
    "masa {sla_days} hari bekerja." + CLOSE,
    "NEEDS_INFO.SCAM": OPEN
    + "Untuk menyemak aduan anda, kami memerlukan sedikit maklumat tambahan. Sila balas dengan tarikh transaksi, "
    "jumlahnya dan nama penerima. {scam_help}" + CLOSE,
    "NOT_COMPLAINT": "{who},\n\nTerima kasih kerana menghubungi pihak bank. Kami tidak menemui sebarang aduan atau "
    "permintaan dalam mesej anda. Jika anda memerlukan bantuan mengenai akaun anda, sila balas dengan butiran dan kami "
    "akan membantu anda." + CLOSE,
    "GENERIC": OPEN
    + "Aduan anda telah kami terima dan pasukan kami sedang menyemaknya. Kami akan memaklumkan perkembangan dalam masa "
    "{sla_days} hari bekerja." + CLOSE,
}
