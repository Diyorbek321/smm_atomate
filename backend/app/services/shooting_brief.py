"""The shot list the owner is asked to film this month.

Everything downstream — the reels engine, the photo card, the video editor —
is a function of the footage it is given. A template cannot rescue a clip shot
in a dark corridor, and a generated "customer" cannot replace a photograph of
the real one. So the highest-leverage thing this system can do is stop waiting
for whatever the owner happens to send and ask for specific frames.

One catalogue per business category, because the advice is only useful when it
is concrete. "Film your product" helps nobody; "hold the phone 20cm above the
plate while the steam is still rising" is a shot. A restaurant, a clinic and a
language centre share the shape of the brief and none of its contents.

Deterministic on purpose, the same division of labour as
:mod:`app.services.promo_families`: the catalogue owns what to shoot and how,
the knowledge base fills in the names, and no model is asked to invent a
production plan. The month index rotates the optional shelves so a client who
stays a year is not handed the same list twelve times.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date

from app.core.plans import PlanCapabilities
from app.models.business import Business
from app.models.enums import BusinessCategory
from app.models.knowledge_base import KnowledgeBase

#: How many shots to ask for. More than this and the owner does none of them.
SHOT_BUDGET = {"photo_only": 6, "with_editing": 10, "full": 14}


@dataclass(frozen=True, slots=True)
class Shot:
    """One frame to capture, described so a phone camera is enough."""

    key: str                     # stable id — survives rotation, useful for tracking
    title: str
    what: str                    # what is in frame
    how: str                     # how to hold the camera
    kind: str = "video"          # "video" | "photo"
    seconds: int = 15
    why: str = ""                # which content this feeds, so it feels worth doing

    def personalised(
        self,
        offering: str,
        person: str,
        *,
        generic_person: bool = False,
        generic_offering: bool = False,
    ) -> Shot:
        """Fill the slots, dropping a title suffix that would only repeat itself.

        «Jamoa a'zosi gapiradi — {person}» with no name in the knowledge base
        renders as «Jamoa a'zosi gapiradi — jamoa a'zosi». The suffix earns its
        place only when there is a real name to put there.
        """
        title = self.title
        if generic_person:
            title = re.sub(r"\s+—\s+\{person\}", "", title)
        if generic_offering:
            title = re.sub(r"\s+—\s+\{offering\}", "", title)

        def fill(text: str) -> str:
            return text.replace("{offering}", offering).replace("{person}", person)

        return Shot(
            key=self.key, title=fill(title), what=fill(self.what), how=fill(self.how),
            kind=self.kind, seconds=self.seconds, why=fill(self.why),
        )


@dataclass(frozen=True, slots=True)
class Catalogue:
    """What one kind of business should film.

    `foundation` goes out every month — without a face, the place and the
    thing being sold, most templates have nothing to open on. The other two
    shelves rotate, which is what stops a month of reels reading as one clip.
    """

    foundation: tuple[Shot, ...]
    proof: tuple[Shot, ...] = ()
    life: tuple[Shot, ...] = ()
    seasonal: dict[int, Shot] = field(default_factory=dict)
    #: What the owner is asked for in place of `{person}` / `{offering}` when
    #: the knowledge base has nothing to put there.
    fallback_person: str = "xodim"
    fallback_offering: str = "asosiy xizmat"
    #: Category-specific warning appended to the notes, when there is one.
    caution: str = ""


@dataclass(slots=True)
class ShootingBrief:
    business: str
    month: date
    shots: list[Shot] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    @property
    def total_seconds(self) -> int:
        return sum(s.seconds for s in self.shots if s.kind == "video")

    @property
    def photo_count(self) -> int:
        return sum(1 for s in self.shots if s.kind == "photo")

    @property
    def video_count(self) -> int:
        return sum(1 for s in self.shots if s.kind == "video")


# --------------------------------------------------------------------------- #
# Education — language centres, academies, tutoring
# --------------------------------------------------------------------------- #

EDUCATION = Catalogue(
    fallback_person="ustoz",
    fallback_offering="asosiy kurs",
    foundation=(
        Shot(key="talking-head", title="Gapiruvchi kadr — resepshn yoki logo devor oldida",
             what="Administrator yoki ustoz kameraga qarab 2-3 gap aytadi",
             how="Telefonni ko'z balandligida vertikal ushlang. Deraza yorug'i yuzga "
                 "tushsin, orqadan emas. Bir dubl — 15 soniya yetadi",
             seconds=20, why="Har reels shu kadr bilan ochiladi"),
        Shot(key="classroom", title="Dars ichi — {offering}",
             what="Ustoz doskada yoki guruh bilan ishlayapti, talabalar kadrda",
             how="Orqa qatordan, ustoz va bir necha talaba birga ko'rinsin. "
                 "Yaqinlashtirmang — xona ko'rinsin",
             seconds=25, why="«Darslar markazda, jonli ustoz bilan» — eng ko'p ishlatiladigan sahna"),
        Shot(key="facade", title="Bino tashqarisi — peshtoq va taxta",
             what="Markaz kirish qismi, nom va logo o'qiladigan darajada",
             how="Ertalab yoki kechqurun — tush paytida soya qattiq tushadi. "
                 "Bir joyda turib, sekin yaqinlashing",
             seconds=12, why="Yopilish kadri: «Qabul boshlandi» shu yerda chiqadi"),
        Shot(key="reception-photo", title="Resepshn — surat",
             what="Kutish zonasi, toza stol, brend ranglari ko'rinadigan burchak",
             how="Gorizontal va vertikal — ikkitasini oling",
             kind="photo", seconds=0, why="Post kartalari fonida ishlatiladi"),
    ),
    proof=(
        Shot(key="student-result", title="Talaba natijasi — o'zi aytadi",
             what="Natijaga erishgan talaba: ismi, qancha vaqtda, qanday ball",
             how="Yozib olishdan oldin bitta gapni kelishib oling: «Men ... oyda ... ga "
                 "chiqdim». Qog'ozdan o'qimasin",
             seconds=25, why="Ijtimoiy isbot posti — eng ko'p ariza shundan keladi"),
        Shot(key="parent-word", title="Ota-ona fikri",
             what="Farzandini olib ketayotgan ota-ona bir-ikki gap aytadi",
             how="Ruxsat so'rang. 15 soniya yetarli, uzun kerak emas",
             seconds=18, why="Ota-ona ovozi ustoz ovozidan kuchliroq ishonch beradi"),
        Shot(key="teacher-intro", title="Ustoz o'zini tanishtiradi — {person}",
             what="Ustoz: ismi, nima o'qitadi, qancha tajriba, bitta yutug'i",
             how="Sinf ichida, doska oldida. Aniq raqam aytsin (ball, yil, talaba soni)",
             seconds=25, why="«40 ta sertifikatlangan ustoz» degan gapga yuz beradi"),
        Shot(key="certificate", title="Sertifikat yoki diplom — surat",
             what="Talabaning haqiqiy sertifikati, ismi ko'rinadigan darajada",
             how="Tekis yuzada, tepadan. Ismni yopmoqchi bo'lsangiz keyin biz yopamiz",
             kind="photo", seconds=0, why="Natija posti uchun"),
    ),
    life=(
        Shot(key="lobby", title="Tanaffus — koridor jonli",
             what="Talabalar chiqib-kirayapti, harakat bor",
             how="Bir joyda turib oling, kamerani silkitmang", seconds=15,
             why="Fon kadri — matn ustiga qo'yiladi"),
        Shot(key="group-work", title="Guruh ishi — stol atrofida",
             what="3-5 talaba birga vazifa bajaryapti",
             how="Yon tomondan, yuzlar ko'rinsin", seconds=18,
             why="«Kichik guruh» degan da'voni ko'rsatadi"),
        Shot(key="speaking", title="Og'zaki mashq",
             what="Ikki talaba yoki ustoz-talaba gaplashyapti",
             how="Yaqindan, lekin yuzni to'liq kadrga oling", seconds=20,
             why="Til markazining eng sotuvchi kadri"),
        Shot(key="hands", title="Qo'l va daftar — yaqin kadr",
             what="Yozayotgan qo'l, daftar, kitob",
             how="Juda yaqin, 20-30 sm. Sekin harakat", seconds=10,
             why="Sahnalar orasidagi ulanish kadri"),
        Shot(key="board", title="Doska — yozuv paydo bo'lishi",
             what="Ustoz doskaga yozayapti", how="Yozuvni o'qib bo'ladigan burchakdan",
             seconds=12, why="Ta'limiy post uchun"),
        Shot(key="app-screen", title="Ilova ekrani — ekran yozuvi",
             what="Platformada dars, jadval yoki natija sahifasi",
             how="Telefon ekranini yozib oling (screen record), 10 soniya",
             seconds=10, why="Platforma haqidagi post uchun"),
        Shot(key="materials", title="O'quv materiallari — surat",
             what="Kitob, daftar, ruchka, markaz brendi bilan",
             how="Tepadan, tabiiy yorug'likda", kind="photo", seconds=0,
             why="Karusel slaydlari foni"),
        Shot(key="team", title="Jamoa — birga surat",
             what="Ustozlar va administratorlar birga",
             how="Peshtoq oldida yoki eng chiroyli xonada", kind="photo", seconds=0,
             why="«Biz kimmiz» posti uchun"),
    ),
    seasonal={
        1: Shot(key="edu-winter-goals", title="Yangi yil maqsadi",
                what="Talaba yoki ustoz: bu yil nimaga erishmoqchi",
                how="Bitta gap, kameraga qarab", seconds=15,
                why="Yanvar — odamlar maqsad qo'yadigan oy"),
        2: Shot(key="edu-exam-prep", title="Imtihonga tayyorgarlik",
                what="Sinov imtihoni yoki mock test payti",
                how="Xona umumiy ko'rinishi + bitta yaqin kadr", seconds=18,
                why="Fevral — imtihon mavsumi"),
        3: Shot(key="edu-spring-intake", title="Bahorgi guruh — birinchi dars",
                what="Yangi guruhning birinchi darsi, tanishuv",
                how="Guruh to'liq kadrda", seconds=20, why="Mart qabuli"),
        4: Shot(key="edu-mock-result", title="Sinov natijasi e'lon qilinishi",
                what="Ustoz natijani aytadi, talaba reaksiyasi",
                how="Reaksiyani o'tkazib yubormang — oldindan yozishni boshlang",
                seconds=20, why="Aprel — sertifikat imtihonlari"),
        5: Shot(key="edu-graduation", title="Sertifikat topshirish",
                what="Talabaga sertifikat berilyapti, qarsak",
                how="Yon tomondan, ikkala yuz ko'rinsin", seconds=20,
                why="May — o'quv yili yakuni"),
        6: Shot(key="edu-summer-start", title="Yozgi intensiv — birinchi kun",
                what="Yozgi guruh, ko'proq yorug'lik, ko'proq harakat",
                how="Tashqarida ham oling", seconds=20, why="Iyun — yozgi qabul"),
        7: Shot(key="edu-summer-life", title="Yozgi dars — tashqarida",
                what="Hovlida yoki ochiq joyda mashg'ulot",
                how="Quyoshni orqangizga olmang", seconds=18, why="Iyul"),
        8: Shot(key="edu-september-ready", title="Sentabrga tayyorgarlik",
                what="Sinflar tozalanyapti, jadval tuzilyapti, yangi kitoblar",
                how="Bir necha qisqa kadr", seconds=20,
                why="Avgust — yilning eng muhim qabul oyi"),
        9: Shot(key="edu-first-day", title="O'quv yili boshlandi",
                what="Birinchi kun, to'la sinf, yangi yuzlar",
                how="Kirish, koridor, sinf — uchta kadr", seconds=25,
                why="Sentabr — eng ko'p qidiruv shu oyda"),
        10: Shot(key="edu-first-month", title="Bir oylik natija",
                 what="Ustoz yoki talaba: bir oyda nima o'zgardi",
                 how="Aniq raqam aytsin", seconds=18, why="Oktabr"),
        11: Shot(key="edu-winter-intake", title="Qishki guruhga qabul",
                 what="Bo'sh joy, yangi jadval, administrator gapiradi",
                 how="Resepshnda", seconds=18, why="Noyabr — qishki qabul"),
        12: Shot(key="edu-year-results", title="Yil yakuni — raqamlar",
                 what="Yil davomidagi natijalar: nechta bitiruvchi, qanday ballar",
                 how="Ustoz aytadi yoki doskaga yozib ko'rsatadi", seconds=22,
                 why="Dekabr — yil yakuni posti"),
    },
)


# --------------------------------------------------------------------------- #
# Food & beverage — restaurants, cafes, bakeries
# --------------------------------------------------------------------------- #

FOOD = Catalogue(
    fallback_person="oshpaz",
    fallback_offering="mashhur taom",
    foundation=(
        Shot(key="chef-talk", title="Oshpaz yoki administrator gapiradi",
             what="Bugungi taom, yangilik yoki bitta maslahat — 2-3 gap",
             how="Oshxona yoki zal fonida, vertikal. Fon shovqini bo'lsa "
                 "telefonni og'izga yaqinroq tuting",
             seconds=20, why="Har reels shu kadr bilan ochiladi"),
        Shot(key="cooking", title="Tayyorlash jarayoni — {offering}",
             what="Taom pishayotgan payt: olov, bug', aralashtirish",
             how="Yaqindan, 30-40 sm. Bug' va olov ko'rinsin — harakat ushlaydi",
             seconds=20, why="Oziq-ovqatda eng ko'p ko'riladigan kadr"),
        Shot(key="dining-room", title="Zal — ichkarida",
             what="Stollar, yorug'lik, odamlar (bo'sh zal emas)",
             how="Eshikdan kirib, sekin o'ngdan chapga. Kechki yorug'likda chiroyliroq",
             seconds=18, why="«Qayerga boraman» degan savolga javob"),
        Shot(key="signature-photo", title="Firma taomi — surat",
             what="Eng mashhur taom, chiroyli tortilgan holda",
             how="Tepadan (90°) va yon tomondan (45°) — ikkitasini oling. "
                 "Deraza yorug'ida, chiroq ostida emas",
             kind="photo", seconds=0, why="Menyu posti va kartalar foni"),
    ),
    proof=(
        Shot(key="guest-word", title="Mehmon fikri",
             what="Ovqatlanib bo'lgan mijoz bir-ikki gap aytadi",
             how="Ruxsat so'rang, stol yonida. 15 soniya yetarli",
             seconds=18, why="Ijtimoiy isbot — eng ishonchli format"),
        Shot(key="kitchen-clean", title="Oshxona ichi — tozalik",
             what="Ish jarayoni, toza yuzalar, tartib",
             how="Bir marta yurib chiqing, to'xtamasdan",
             seconds=20, why="Oziq-ovqatda eng katta e'tiroz — tozalik"),
        Shot(key="ingredients", title="Yangi masalliqlar keldi",
             what="Ertalabki mahsulot: go'sht, sabzavot, non",
             how="Qadoqdan chiqarilayotgan payt", seconds=15,
             why="«Yangi mahsulotdan» da'vosini ko'rsatadi"),
        Shot(key="team-photo", title="Jamoa — surat",
             what="Oshpazlar va ofitsiantlar birga",
             how="Oshxona yoki zal oldida", kind="photo", seconds=0,
             why="«Biz kimmiz» posti"),
    ),
    life=(
        Shot(key="plating", title="Tortish payti — tarelka bezatilishi",
             what="Taom tarelkaga qo'yilyapti, oxirgi shtrix",
             how="Tepadan, qo'l ko'rinsin", seconds=12, why="Eng estetik kadr"),
        Shot(key="pour", title="Ichimlik quyilishi",
             what="Choy, kofe yoki sharbat quyilayotgan payt",
             how="Yon tomondan, sekin harakat", seconds=10,
             why="Sahnalar orasidagi ulanish"),
        Shot(key="steam", title="Bug' va olov — yaqin kadr",
             what="Qozon, tandir yoki gril ustidagi harakat",
             how="Juda yaqin. Fokusni bug'ga qo'ying", seconds=10,
             why="Ochlik uyg'otadigan kadr"),
        Shot(key="table-set", title="Stol tayyorlanishi",
             what="Ochilishdan oldin stol qo'yilyapti", how="Tepadan yoki yon tomondan",
             seconds=12, why="Fon kadri"),
        Shot(key="delivery", title="Yetkazib berish — qadoqlash",
             what="Buyurtma qadoqlanyapti, kuryerga berilyapti",
             how="Qadoq brendi ko'rinsin", seconds=15, why="Yetkazib berish posti"),
        Shot(key="menu-photo", title="Menyu — surat",
             what="Menyu yoki narx taxtasi, o'qiladigan darajada",
             how="Tekis, to'g'ri burchakdan", kind="photo", seconds=0,
             why="Narx posti uchun"),
        Shot(key="interior-detail", title="Interyer detali — surat",
             what="Chiroq, devor, o'simlik — joyni tanitadigan burchak",
             how="Yaqindan", kind="photo", seconds=0, why="Karusel foni"),
    ),
    seasonal={
        3: Shot(key="food-navruz", title="Navro'z taomlari",
                what="Sumalak, ko'k somsa — mavsumiy taom",
                how="Tayyorlash jarayonini ham oling", seconds=20, why="Mart — Navro'z"),
        6: Shot(key="food-summer-drink", title="Salqin ichimlik",
                what="Muzli ichimlik, tomchi bilan", how="Yon tomondan, muz ko'rinsin",
                seconds=12, why="Iyun — issiqda salqin sotiladi"),
        7: Shot(key="food-terrace", title="Ochiq havoda — terrasa",
                what="Tashqaridagi stollar, kechki yorug'lik",
                how="Quyosh botayotganda", seconds=15, why="Iyul — tashqarida o'tirish"),
        11: Shot(key="food-warm", title="Issiq taom — qish menyusi",
                 what="Bug'lanayotgan sho'rva yoki issiq taom",
                 how="Bug' aniq ko'rinsin, sovuq fonda", seconds=15,
                 why="Noyabr — issiq taom mavsumi"),
        12: Shot(key="food-newyear", title="Yangi yil bandlovi",
                 what="Bezatilgan zal, bayram stoli",
                 how="Kechqurun, chiroqlar yoqilgan holda", seconds=18,
                 why="Dekabr — korporativ bandlov"),
    },
)


# --------------------------------------------------------------------------- #
# Retail & e-commerce — shops, showrooms, online stores
# --------------------------------------------------------------------------- #

RETAIL = Catalogue(
    fallback_person="sotuvchi",
    fallback_offering="mashhur mahsulot",
    foundation=(
        Shot(key="seller-talk", title="Sotuvchi yoki ega gapiradi",
             what="Yangi tovar, chegirma yoki bitta maslahat — 2-3 gap",
             how="Do'kon ichida, tovar fonida. Vertikal, ko'z balandligida",
             seconds=20, why="Har reels shu kadr bilan ochiladi"),
        Shot(key="product-closeup", title="Mahsulot — yaqin kadr — {offering}",
             what="Tovar qo'lda aylantirilyapti, detallar ko'rinadi",
             how="Yaqindan, sekin aylantiring. Yorug'lik bir tomondan tushsin",
             seconds=15, why="Sotuv posti — mahsulot ko'rinmasa post ishlamaydi"),
        Shot(key="shop-inside", title="Do'kon ichi",
             what="Javonlar, tartib, tovar ko'pligi",
             how="Eshikdan kirib, sekin yuring", seconds=18,
             why="«Bu yerda tanlov bor» degan xabar"),
        Shot(key="storefront-photo", title="Peshtoq — surat",
             what="Kirish, nom, vitrina", how="Ertalab yoki kechqurun",
             kind="photo", seconds=0, why="Yopilish kadri"),
    ),
    proof=(
        Shot(key="customer-word", title="Xaridor fikri",
             what="Xarid qilgan mijoz nima olgani va nega olgani haqida",
             how="Kassа yonida, ruxsat bilan", seconds=18,
             why="Ijtimoiy isbot"),
        Shot(key="in-use", title="Mahsulot ishlatilayotgan payt",
             what="Tovar haqiqiy holatda: kiyilgan, ishlatilgan, o'rnatilgan",
             how="Do'konda emas, hayotda — imkon bo'lsa", seconds=18,
             why="«Menga to'g'ri keladimi» savoliga javob"),
        Shot(key="packing", title="Buyurtma qadoqlanyapti",
             what="Tovar qutiga solinyapti, brend qadog'i bilan",
             how="Tepadan, qo'l ko'rinsin", seconds=15,
             why="Onlayn buyurtma posti"),
        Shot(key="review-photo", title="Mijoz sharhi — skrinshot",
             what="Haqiqiy sharh yoki rahmat xabari",
             how="Ism yopilsa ham bo'ladi", kind="photo", seconds=0,
             why="Isbot posti"),
    ),
    life=(
        Shot(key="new-arrival", title="Yangi tovar keldi",
             what="Quti ochilyapti, ichidan tovar chiqyapti",
             how="Ochilish paytini o'tkazib yubormang", seconds=15,
             why="«Yangi keldi» posti — eng tez ishlaydigan format"),
        Shot(key="shelf-order", title="Javon tartibi",
             what="Tovarlar tartib bilan terilgan", how="Sekin yon harakat",
             seconds=12, why="Fon kadri"),
        Shot(key="try-on", title="Kiyib yoki sinab ko'rish",
             what="Mijoz tovarni sinab ko'ryapti", how="Ruxsat bilan, yuzsiz ham bo'ladi",
             seconds=15, why="Jarayonni ko'rsatadi"),
        Shot(key="price-tag", title="Narx yorlig'i — surat",
             what="Narx aniq o'qiladigan yorliq", how="Yaqindan, tekis",
             kind="photo", seconds=0, why="Narx posti uchun"),
        Shot(key="range-photo", title="Assortiment — surat",
             what="Bir turdagi tovarning barcha rang/o'lchamlari",
             how="Tepadan, tartib bilan terib", kind="photo", seconds=0,
             why="Karusel uchun"),
        Shot(key="workday", title="Ish kuni boshlanishi",
             what="Do'kon ochilyapti, chiroq yoqilyapti", how="Bir joyda turib",
             seconds=12, why="«Bugun ishlaymiz» story uchun"),
    ),
    seasonal={
        3: Shot(key="retail-mart", title="8-mart tanlovi",
                what="Sovg'aga mos tovarlar birga", how="Tepadan, tartib bilan",
                seconds=15, why="Mart — sovg'a mavsumi"),
        8: Shot(key="retail-school", title="Maktabga tayyorgarlik",
                what="O'quv yiliga kerakli tovarlar", how="Tepadan",
                seconds=15, why="Avgust — maktab xaridi"),
        11: Shot(key="retail-sale", title="Chegirma — yorliqlar",
                 what="Chegirma yorliqlari, eski va yangi narx",
                 how="Yaqindan, ikkala raqam ko'rinsin", seconds=12,
                 why="Noyabr — chegirma mavsumi"),
        12: Shot(key="retail-gift", title="Yangi yil sovg'asi — qadoqlash",
                 what="Sovg'a qadoqlanyapti", how="Qo'l va lenta ko'rinsin",
                 seconds=15, why="Dekabr — sovg'a xaridi"),
    },
)


# --------------------------------------------------------------------------- #
# Beauty — salons, barbershops, cosmetology
# --------------------------------------------------------------------------- #

BEAUTY = Catalogue(
    fallback_person="usta",
    fallback_offering="mashhur xizmat",
    foundation=(
        Shot(key="master-talk", title="Usta gapiradi",
             what="Bitta maslahat yoki bugungi ish haqida 2-3 gap",
             how="Ish joyida, oyna fonida bo'lmasin — aks etadi",
             seconds=20, why="Har reels shu kadr bilan ochiladi"),
        Shot(key="process", title="Ish jarayoni — {offering}",
             what="Xizmat ko'rsatilayotgan payt: qaychi, cho'tka, qo'l harakati",
             how="Yaqindan, qo'l va natija ko'rinsin. Mijoz yuzi shart emas",
             seconds=20, why="Go'zallikda jarayon natijadan ko'ra ko'proq ko'riladi"),
        Shot(key="salon-inside", title="Salon ichi",
             what="Ish joylari, tozalik, yorug'lik", how="Eshikdan kirib, sekin yuring",
             seconds=15, why="«Qayerga boraman» savoliga javob"),
        Shot(key="result-photo", title="Natija — surat",
             what="Tugagan ish, eng yaxshi burchakdan",
             how="Bir xil joyda, bir xil yorug'likda oling — feed bir butun ko'rinadi",
             kind="photo", seconds=0, why="Asosiy sotuv kadri"),
    ),
    proof=(
        Shot(key="before-after", title="Oldin va keyin",
             what="Bir mijozning ikki holati", how="Bir xil burchak, bir xil yorug'lik. "
                 "Ruxsat majburiy",
             seconds=15, why="Go'zallikda eng kuchli isbot"),
        Shot(key="client-word", title="Mijoz fikri",
             what="Ish tugagach mijoz bir-ikki gap aytadi", how="Ruxsat bilan, oyna oldida",
             seconds=18, why="Ishonch"),
        Shot(key="master-cert", title="Usta sertifikati — surat",
             what="O'qish yoki malaka hujjati", how="Tekis, o'qiladigan darajada",
             kind="photo", seconds=0, why="«Kim qiladi» savoliga javob"),
        Shot(key="detail-work", title="Nozik ish — juda yaqin kadr",
             what="Qo'l ishi eng aniq ko'rinadigan payt", how="15-20 sm dan",
             seconds=12, why="Mahorat ko'rsatadi"),
    ),
    life=(
        Shot(key="tools", title="Asboblar — surat",
             what="Toza asboblar tartib bilan", how="Tepadan",
             kind="photo", seconds=0, why="Tozalik e'tiroziga javob"),
        Shot(key="mixing", title="Aralashtirish — bo'yoq yoki modda",
             what="Modda tayyorlanyapti", how="Yaqindan, rang ko'rinsin",
             seconds=12, why="Jarayon kadri"),
        Shot(key="wash", title="Yuvish yoki tozalash bosqichi",
             what="Oraliq bosqich", how="Yon tomondan", seconds=12,
             why="Ulanish kadri"),
        Shot(key="final-touch", title="Oxirgi shtrix",
             what="Ish yakunlanayotgan payt", how="Yaqindan", seconds=12,
             why="Natijaga o'tish"),
        Shot(key="reaction", title="Mijoz reaksiyasi",
             what="Oynada o'zini ko'rgan payt", how="Ruxsat bilan. Reaksiyani kutmang — "
                 "oldindan yozishni boshlang",
             seconds=12, why="Eng samimiy kadr"),
        Shot(key="workspace-photo", title="Ish joyi — surat",
             what="Kreslo, oyna, brend detallari", how="Tabiiy yorug'likda",
             kind="photo", seconds=0, why="Karusel foni"),
    ),
    caution="Mijoz yuzi yoki oldin/keyin kadri uchun OG'ZAKI EMAS, yozma ruxsat oling.",
)


# --------------------------------------------------------------------------- #
# Healthcare — clinics, dental, diagnostics
# --------------------------------------------------------------------------- #

HEALTHCARE = Catalogue(
    fallback_person="shifokor",
    fallback_offering="asosiy xizmat",
    foundation=(
        Shot(key="doctor-talk", title="Shifokor gapiradi — {person}",
             what="Bitta savolga aniq javob yoki profilaktika maslahati",
             how="Kabinetda, oq xalatda. Kameraga qarab, sekin gapirsin",
             seconds=25, why="Tibbiyotda ishonch shifokor yuzidan boshlanadi"),
        Shot(key="clinic-inside", title="Klinika ichi — koridor va qabulxona",
             what="Toza, yorug', bemorsiz", how="Sekin yurib o'ting",
             seconds=15, why="«Qayerga boraman» savoliga javob"),
        Shot(key="equipment", title="Jihoz — {offering}",
             what="Asosiy jihoz, ishlayotgan yoki tayyor holatda",
             how="Yaqindan, nomi ko'rinsa yaxshi", seconds=15,
             why="«Zamonaviy jihoz» da'vosini ko'rsatadi — aytish emas"),
        Shot(key="reception-photo", title="Registratura — surat",
             what="Qabul stoli, tartib", how="Gorizontal va vertikal",
             kind="photo", seconds=0, why="Kartalar foni"),
    ),
    proof=(
        Shot(key="patient-word", title="Bemor fikri",
             what="Davolangan bemor natijasi haqida",
             how="YOZMA ruxsat majburiy. Tashxis aytilmasin — faqat taassurot",
             seconds=20, why="Eng kuchli isbot, eng ehtiyot bo'ladigan format"),
        Shot(key="diploma", title="Diplom va sertifikatlar — surat",
             what="Shifokor hujjatlari", how="Tekis, o'qiladigan darajada",
             kind="photo", seconds=0, why="Malaka isboti"),
        Shot(key="procedure", title="Jarayon — bemorsiz",
             what="Muolaja yoki tekshiruv qanday ketishi, ko'rsatib berilgan holda",
             how="Xodim ko'rsatadi, haqiqiy bemor emas", seconds=20,
             why="Qo'rquvni kamaytiradi"),
        Shot(key="sterile", title="Sterilizatsiya",
             what="Asboblar tozalanishi, qadoqlanishi", how="Yaqindan",
             seconds=15, why="Tibbiyotdagi asosiy e'tiroz"),
    ),
    life=(
        Shot(key="team", title="Jamoa — surat", what="Shifokorlar va hamshiralar",
             how="Klinika ichida", kind="photo", seconds=0, why="«Biz kimmiz»"),
        Shot(key="consult", title="Maslahat payti — yuzsiz",
             what="Shifokor tushuntiryapti, bemor orqadan",
             how="Bemor tanilmasin", seconds=15, why="Jarayon kadri"),
        Shot(key="lab", title="Tahlil yoki laboratoriya",
             what="Namuna olish yoki tekshirish", how="Yaqindan, yuzsiz",
             seconds=12, why="Xizmatlar posti"),
        Shot(key="waiting", title="Kutish zonasi",
             what="Qulay o'rindiqlar, toza joy", how="Bir joyda turib",
             seconds=12, why="Fon kadri"),
        Shot(key="schedule-photo", title="Ish jadvali — surat",
             what="Qabul vaqtlari taxtasi", how="Tekis, o'qiladigan",
             kind="photo", seconds=0, why="Ma'lumot posti"),
    ),
    caution="Bemor yuzi, tashxisi yoki hujjati — faqat YOZMA ruxsat bilan. "
            "Davolash natijasini kafolat sifatida ko'rsatmang.",
)


# --------------------------------------------------------------------------- #
# Real estate
# --------------------------------------------------------------------------- #

REAL_ESTATE = Catalogue(
    fallback_person="agent",
    fallback_offering="obyekt",
    foundation=(
        Shot(key="agent-talk", title="Agent gapiradi — {person}",
             what="Obyekt haqida: narx, joy, xonalar soni — aniq raqamlar bilan",
             how="Obyekt oldida yoki ichida. Vertikal", seconds=25,
             why="Har reels shu kadr bilan ochiladi"),
        Shot(key="walkthrough", title="Ichkariga kirish — {offering}",
             what="Eshikdan kirib, xonalar bo'ylab yurish",
             how="Sekin va tekis yuring, to'xtamang. Barcha chiroqlarni yoqing, "
                 "pardalarni oching",
             seconds=30, why="Ko'chmas mulkda asosiy format"),
        Shot(key="facade", title="Bino tashqarisi",
             what="Fasad, kirish, atrof", how="Kunduzi, soya kam bo'lganda",
             seconds=15, why="Yopilish kadri"),
        Shot(key="best-room-photo", title="Eng yaxshi xona — surat",
             what="Yorug' va keng ko'rinadigan xona",
             how="Burchakdan, deraza tomonga qarab", kind="photo", seconds=0,
             why="E'lon kartasining asosiy rasmi"),
    ),
    proof=(
        Shot(key="handover", title="Kalit topshirish",
             what="Mijoz kalit olayotgan payt", how="Ikkala yuz ko'rinsin, ruxsat bilan",
             seconds=15, why="Bitim bo'lganini ko'rsatadi"),
        Shot(key="client-word", title="Xaridor fikri",
             what="Uy olgan mijoz taassuroti", how="Yangi uyda, ruxsat bilan",
             seconds=18, why="Ishonch"),
        Shot(key="renovation", title="Ta'mirdan oldin va keyin",
             what="Bir xonaning ikki holati", how="Bir xil burchakdan",
             seconds=15, why="Qiymat oshganini ko'rsatadi"),
        Shot(key="documents-photo", title="Hujjat — surat",
             what="Kadastr yoki shartnoma (raqamlar yopilgan)",
             how="Tekis", kind="photo", seconds=0, why="Qonuniylik isboti"),
    ),
    life=(
        Shot(key="view", title="Deraza manzarasi",
             what="Derazadan ko'rinish", how="Derazaga yaqin turib, tashqariga fokus",
             seconds=12, why="Ko'p qaror shu kadrga bog'liq"),
        Shot(key="yard", title="Hovli va atrof",
             what="Bino atrofi, o'tirish joyi, avtoturargoh", how="Sekin yurib",
             seconds=15, why="«Atrofi qanday» savoliga javob"),
        Shot(key="infrastructure", title="Yaqin atrof — infratuzilma",
             what="Maktab, do'kon, bekat — piyoda masofada",
             how="Yurib borgan holda", seconds=20, why="Joylashuv posti"),
        Shot(key="kitchen", title="Oshxona — detal",
             what="Oshxona jihozi, ish yuzasi", how="Burchakdan", seconds=12,
             why="Xaridor eng ko'p so'raydigan xona"),
        Shot(key="plan-photo", title="Rejasi — surat",
             what="Xonalar rejasi yoki chizma", how="Tekis, o'qiladigan",
             kind="photo", seconds=0, why="Karusel uchun"),
    ),
)


# --------------------------------------------------------------------------- #
# Tech / services / anything else
# --------------------------------------------------------------------------- #

TECH = Catalogue(
    fallback_person="jamoa a'zosi",
    fallback_offering="asosiy mahsulot",
    foundation=(
        Shot(key="team-talk", title="Jamoa a'zosi gapiradi — {person}",
             what="Nima ustida ishlayapmiz yoki bitta texnik maslahat",
             how="Ish joyida, ekran fonida. Vertikal", seconds=25,
             why="Har reels shu kadr bilan ochiladi"),
        Shot(key="product-screen", title="Mahsulot ekrani — ekran yozuvi — {offering}",
             what="Interfeys, haqiqiy ma'lumot bilan (test ma'lumot emas)",
             how="Ekran yozuvi (screen record), 15-20 soniya. Sichqoncha sekin harakat qilsin",
             seconds=20, why="Mahsulot ko'rinmasa post ishonchsiz"),
        Shot(key="office", title="Ish joyi",
             what="Ofis yoki ish stoli, jonli holatda", how="Sekin yon harakat",
             seconds=15, why="Fon kadri"),
        Shot(key="brand-photo", title="Brend detali — surat",
             what="Logo, stiker, futbolka yoki ish stoli", how="Yaqindan",
             kind="photo", seconds=0, why="Kartalar foni"),
    ),
    proof=(
        Shot(key="client-result", title="Mijoz natijasi",
             what="Raqam bilan: nima o'zgardi, qancha vaqtda",
             how="Ekran yoki grafik ko'rsatib", seconds=20, why="Keys posti"),
        Shot(key="client-word", title="Mijoz fikri",
             what="Mijoz nima hal bo'lganini aytadi", how="Onlayn yozuv ham bo'ladi",
             seconds=20, why="Ishonch"),
        Shot(key="before-after-screen", title="Oldin va keyin — ekran",
             what="Eski va yangi interfeys yoki natija", how="Ikki ekran yozuvi",
             seconds=15, why="Ish ko'rinadi"),
        Shot(key="metric-photo", title="Ko'rsatkich — skrinshot",
             what="Haqiqiy grafik yoki panel", how="Maxfiy ma'lumot yopilsin",
             kind="photo", seconds=0, why="Raqamli isbot"),
    ),
    life=(
        Shot(key="whiteboard", title="Doska — rejalashtirish",
             what="Sxema chizilyapti yoki muhokama", how="Yon tomondan",
             seconds=15, why="Jarayon kadri"),
        Shot(key="code", title="Ekran — ish payti",
             what="Kod, dizayn yoki hujjat ustida ish", how="Ekran yozuvi yoki yelka ustidan",
             seconds=12, why="Ulanish kadri"),
        Shot(key="standup", title="Jamoa muhokamasi",
             what="Qisqa yig'ilish, harakat bor", how="Bir joyda turib",
             seconds=15, why="«Biz kimmiz» posti"),
        Shot(key="demo", title="Mahsulot demosi — 3 qadam",
             what="Foydalanuvchi bitta ishni qanday bajaradi",
             how="Ekran yozuvi, uchta qadam, izohsiz", seconds=20,
             why="Eng ko'p saqlanadigan format"),
        Shot(key="desk-photo", title="Ish stoli — surat",
             what="Tartibli stol, texnika", how="Tepadan", kind="photo", seconds=0,
             why="Karusel foni"),
    ),
)

GENERIC = Catalogue(
    foundation=(
        Shot(key="owner-talk", title="Ega yoki xodim gapiradi",
             what="Kameraga qarab 2-3 gap: bugun nima yangilik",
             how="Vertikal, ko'z balandligida, deraza yorug'ida", seconds=20,
             why="Har reels shu kadr bilan ochiladi"),
        Shot(key="place", title="Joy — ichkarida",
             what="Ish jarayoni, odamlar, harakat",
             how="Bir joyda turib, sekin o'ngdan chapga", seconds=20,
             why="Fon kadri"),
        Shot(key="product", title="Mahsulot yoki xizmat — {offering}",
             what="Siz sotadigan narsa, eng chiroyli holatda",
             how="Yaqindan, tabiiy yorug'likda", seconds=15, why="Sotuv posti uchun"),
        Shot(key="storefront", title="Peshtoq — surat", what="Kirish, nom, logo",
             how="Ertalab yoki kechqurun", kind="photo", seconds=0,
             why="Yopilish kadri"),
    ),
    proof=(
        Shot(key="client-word", title="Mijoz fikri",
             what="Xizmatdan foydalangan mijoz 2-3 gap aytadi",
             how="Ruxsat so'rang, 15 soniya yetarli", seconds=18,
             why="Ijtimoiy isbot — eng ishonchli format"),
        Shot(key="process", title="Ish jarayoni",
             what="Xizmat qanday bajarilishi", how="Yaqindan, qo'l ko'rinsin",
             seconds=18, why="«Nima uchun to'layman» savoliga javob"),
        Shot(key="team-photo", title="Jamoa — surat", what="Xodimlar birga",
             how="Ish joyi oldida", kind="photo", seconds=0, why="«Biz kimmiz» posti"),
    ),
    life=(
        Shot(key="detail", title="Detal — yaqin kadr",
             what="Ishning eng aniq ko'rinadigan qismi", how="20-30 sm dan",
             seconds=10, why="Ulanish kadri"),
        Shot(key="workday", title="Ish kuni boshlanishi",
             what="Ochilish, tayyorgarlik", how="Bir joyda turib", seconds=12,
             why="Story uchun"),
        Shot(key="tools-photo", title="Asbob yoki jihoz — surat",
             what="Ishlatiladigan asboblar", how="Tepadan", kind="photo", seconds=0,
             why="Karusel foni"),
    ),
)

CATALOGUES: dict[BusinessCategory, Catalogue] = {
    BusinessCategory.EDUCATION: EDUCATION,
    BusinessCategory.FOOD_BEVERAGE: FOOD,
    BusinessCategory.RETAIL: RETAIL,
    BusinessCategory.ECOMMERCE: RETAIL,
    BusinessCategory.BEAUTY: BEAUTY,
    BusinessCategory.HEALTHCARE: HEALTHCARE,
    BusinessCategory.REAL_ESTATE: REAL_ESTATE,
    BusinessCategory.TECH: TECH,
    BusinessCategory.OTHER: GENERIC,
}


def catalogue_for(category: BusinessCategory) -> Catalogue:
    return CATALOGUES.get(category, GENERIC)


# --------------------------------------------------------------------------- #
def _budget(capabilities: PlanCapabilities) -> int:
    if capabilities.video:
        return SHOT_BUDGET["full"]
    if capabilities.video_editing:
        return SHOT_BUDGET["with_editing"]
    return SHOT_BUDGET["photo_only"]


def _rotate(pool: tuple[Shot, ...], count: int, offset: int) -> list[Shot]:
    """Take `count` shots, starting at a point that moves every month."""
    if not pool or count <= 0:
        return []
    start = offset % len(pool)
    return [pool[(start + i) % len(pool)] for i in range(min(count, len(pool)))]


def _offering_name(knowledge: KnowledgeBase | None, fallback: str) -> str:
    for entry in (knowledge.key_offerings if knowledge else None) or []:
        name = str(entry.get("name", "")).strip()
        if name:
            return name
    return fallback


def _person_name(knowledge: KnowledgeBase | None, fallback: str) -> str:
    """A real name from the base if there is one.

    `teacher_profiles` is named for the first category this system served; it
    holds whoever fronts the business — a chef, a doctor, an agent.
    """
    for entry in (knowledge.teacher_profiles if knowledge else None) or []:
        name = str(entry.get("name", "")).strip()
        if name:
            return name
    return fallback


def build_brief(
    business: Business,
    knowledge: KnowledgeBase | None,
    month: date | None = None,
    *,
    footage_on_hand: int = 0,
) -> ShootingBrief:
    """The shot list for one month, personalised and rotated.

    `footage_on_hand` is what the business has already sent. A client with an
    empty shelf is asked for the foundation and proof; one with a library gets
    more of the rotating shelf, because the gap in their feed is variety, not
    basics.
    """
    month = month or date.today().replace(day=1)
    offset = month.year * 12 + month.month
    catalogue = catalogue_for(business.category)
    capabilities = business.capabilities

    budget = _budget(capabilities)
    shots = list(catalogue.foundation)
    remaining = max(0, budget - len(shots))

    # Proof before variety: the first month should produce posts that sell.
    proof_share = 3 if footage_on_hand < 6 else 2
    proof = _rotate(catalogue.proof, min(proof_share, remaining), offset)
    remaining -= len(proof)

    seasonal_shot = catalogue.seasonal.get(month.month)
    seasonal = [seasonal_shot] if seasonal_shot and remaining > 0 else []
    remaining -= len(seasonal)

    life = _rotate(catalogue.life, remaining, offset)
    shots = shots + proof + seasonal + life

    offering = _offering_name(knowledge, catalogue.fallback_offering)
    person = _person_name(knowledge, catalogue.fallback_person)
    shots = [
        shot.personalised(
            offering,
            person,
            generic_person=person == catalogue.fallback_person,
            generic_offering=offering == catalogue.fallback_offering,
        )
        for shot in shots
    ][:budget]

    return ShootingBrief(
        business=business.name,
        month=month,
        shots=shots,
        notes=_notes(capabilities, footage_on_hand, catalogue),
    )


def _notes(
    capabilities: PlanCapabilities, footage_on_hand: int, catalogue: Catalogue
) -> list[str]:
    notes = [
        "Telefon yetarli — professional kamera shart emas.",
        "Vertikal oling (9:16). Gorizontal kadrni kesib ishlatamiz, sifat yo'qoladi.",
        "Har kadrni bir marta oling va keyingisiga o'ting — qayta olishga urinmang.",
    ]
    if catalogue.caution:
        notes.append(f"⚠️ {catalogue.caution}")
    if not capabilities.video and not capabilities.video_editing:
        notes.append(
            "Tarifingizda video montaj yo'q — suratlar post kartalari uchun ishlatiladi."
        )
    if footage_on_hand == 0:
        notes.append(
            "Bu birinchi brif. Hammasini bir kunda olsangiz, oylik kontent shundan chiqadi."
        )
    return notes


MONTH_NAMES = (
    "yanvar", "fevral", "mart", "aprel", "may", "iyun",
    "iyul", "avgust", "sentabr", "oktabr", "noyabr", "dekabr",
)


def render_telegram(brief: ShootingBrief) -> str:
    """The brief as one Telegram message the owner can work from."""
    lines = [
        f"🎬 <b>{MONTH_NAMES[brief.month.month - 1].capitalize()} — suratga olish brifi</b>",
        f"{brief.business}",
        "",
        f"{brief.video_count} ta video · {brief.photo_count} ta surat · "
        f"jami ~{brief.total_seconds} soniya material",
        "",
    ]
    for index, shot in enumerate(brief.shots, 1):
        badge = "📷" if shot.kind == "photo" else "🎥"
        head = f"{index}. {badge} <b>{shot.title}</b>"
        if shot.kind == "video":
            head += f" — {shot.seconds}s"
        lines.append(head)
        lines.append(f"   {shot.what}")
        lines.append(f"   <i>{shot.how}</i>")
        if shot.why:
            lines.append(f"   → {shot.why}")
        lines.append("")

    lines.append("<b>Eslatma</b>")
    lines.extend(f"• {note}" for note in brief.notes)
    return "\n".join(lines)
