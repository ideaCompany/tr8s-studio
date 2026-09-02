#!/usr/bin/env python3
"""
30 style arcs for the TR-8S, 8 variations each (A-H).

Each style occupies one pattern slot; its 8 variations form a performable arc:
    A intro   B main    C variant  D alt
    E break   F peak    G fill     H outro

Step string notation, one character per 16th note, 16 per bar:
    X accent (vel 112)   x normal (vel 100)   o ghost (vel 55)   . rest

Tracks are the TR-8S panel instruments:
    BD SD LT MT HT RS HC CH OH CC RC
"""

S = lambda **kw: kw  # noqa: E731  -- terse track dict


STYLES = {

# ------------------------------------------------------------------ TECHNO

"techno_peak": dict(bpm=134, swing=0.0, patterns=[
 ("A_intro",   S(BD="X...x...X...x...", CH="..x...x...x...x.")),
 ("B_main",    S(BD="X...x...X...x...", CH="x.x.x.x.x.x.x.x.", OH="..x...x...x...x.", RS="....x.......x...")),
 ("C_variant", S(BD="X...x...X...x...", CH="xoxoxoxoxoxoxoxo", OH="..x...x...x...x.", HC="....X.......X...")),
 ("D_alt",     S(BD="X...x...X...x..x", CH="x.xox.xox.xox.xo", OH="..x...x...x...x.", RC="....x.......x...")),
 ("E_break",   S(CH="xoxoxoxoxoxoxoxo", OH="..x...x...x...x.", HC="....X.......X...", RC="x...x...x...x...")),
 ("F_peak",    S(BD="X...X...X...X...", CH="xoxoxoxoxoxoxoxo", OH="..x...x...x...x.", HC="....X.......X...", CC="X...............")),
 ("G_fill",    S(BD="X...x...X.......", CH="x.x.x.x.x.......", LT="..........x.x...", MT="..............x.", HT="...............X", CC="X...............")),
 ("H_outro",   S(BD="X...x...X...x...", RC="..o...o...o...o.")),
]),

"techno_hypnotic": dict(bpm=132, swing=0.0, patterns=[
 ("A_intro",   S(BD="X.......X.......", RC="..o...o...o...o.")),
 ("B_main",    S(BD="X...x...X...x...", RC="x.o.x.o.x.o.x.o.", RS="......o.......o.")),
 ("C_variant", S(BD="X...x...X...x...", RC="x.o.x.o.x.o.x.o.", OH="......x.......x.", RS="....o.......o...")),
 ("D_alt",     S(BD="X...x...X...x...", CH="x.oox.oox.oox.oo", LT="..........o.....", RS="......o.......o.")),
 ("E_break",   S(RC="x.o.x.o.x.o.x.o.", LT="....o.......o...", MT="..........o.....")),
 ("F_peak",    S(BD="X...x...X...x...", CH="xoxoxoxoxoxoxoxo", OH="..x...x...x...x.", RC="x...x...x...x...")),
 ("G_fill",    S(BD="X...x...X.......", LT="........o.o.....", MT="............o.o.", HT="..............oX")),
 ("H_outro",   S(BD="X.......X.......", RC="..o...o...o...o.")),
]),

"techno_industrial": dict(bpm=140, swing=0.0, patterns=[
 ("A_intro",   S(BD="X...X...X...X...", CH="....x.......x...")),
 ("B_main",    S(BD="X...X...X...X...", CH="x.x.x.x.x.x.x.x.", HC="....X.......X...")),
 ("C_variant", S(BD="X..XX...X..XX...", CH="xoxoxoxoxoxoxoxo", HC="....X.......X...")),
 ("D_alt",     S(BD="X...X...X...X...", CH="xoxoxoxoxoxoxoxo", MT="......o.......o.", LT="..........o.....")),
 ("E_break",   S(CH="xoxoxoxoxoxoxoxo", HC="....X.......X...", CC="X.......X.......")),
 ("F_peak",    S(BD="X..XX..XX..XX..X", CH="xoxoxoxoxoxoxoxo", HC="....X.......X...", CC="X...............")),
 ("G_fill",    S(BD="X...X...X.......", LT="........X.X.....", MT="............X.X.", HT="..............XX")),
 ("H_outro",   S(BD="X...X...X...X...", CH="....x.......x...")),
]),

"techno_dub": dict(bpm=126, swing=0.0, patterns=[
 ("A_intro",   S(BD="X.......X.......", RC="......o.......o.")),
 ("B_main",    S(BD="X...x...X...x...", OH="..x...x...x...x.", RS="......o.......o.")),
 ("C_variant", S(BD="X...x...X...x...", OH="..x...x...x...x.", CH="x...x...x...x...", RS="....o.......o...")),
 ("D_alt",     S(BD="X...x...X...x...", OH="..x...x...x...x.", LT="..........o.....", RC="x.......x.......")),
 ("E_break",   S(OH="..x...x...x...x.", RC="x...x...x...x...", RS="....o.......o...")),
 ("F_peak",    S(BD="X...x...X...x...", OH="..x...x...x...x.", CH="x.o.x.o.x.o.x.o.", HC="....X.......X...")),
 ("G_fill",    S(BD="X...x...X.......", OH="..x...x.........", LT="..........o.o...", MT="..............o.")),
 ("H_outro",   S(BD="X.......X.......", OH="..x...x...x...x.")),
]),

"techno_acid": dict(bpm=136, swing=0.0, patterns=[
 ("A_intro",   S(BD="X...x...X...x...", CH="..x...x...x...x.")),
 ("B_main",    S(BD="X...x...X...x...", CH="x.x.x.x.x.x.x.x.", RS="..o...o...o...o.")),
 ("C_variant", S(BD="X...x...X...x..x", CH="xoxoxoxoxoxoxoxo", RS="....x.......x...")),
 ("D_alt",     S(BD="X...x...X...x...", OH="..x...x...x...x.", CH="x.o.x.o.x.o.x.o.", HC="............X...")),
 ("E_break",   S(CH="xoxoxoxoxoxoxoxo", RS="..o...o...o...o.", RC="x...x...x...x...")),
 ("F_peak",    S(BD="X...X...X...X...", CH="xoxoxoxoxoxoxoxo", OH="..x...x...x...x.", CC="X...............")),
 ("G_fill",    S(BD="X...x...X.......", CH="x.x.x.x.........", LT="........o.o.o...", HT="..............oX")),
 ("H_outro",   S(BD="X...x...X...x...", CH="..o...o...o...o.")),
]),

"techno_hardgroove": dict(bpm=138, swing=0.08, patterns=[
 ("A_intro",   S(BD="X...x...X...x...", CH="..x...x...x...x.")),
 ("B_main",    S(BD="X...x...X...x...", CH="xoxoxoxoxoxoxoxo", RS="..o.x.....o.x...")),
 ("C_variant", S(BD="X...x..xX...x...", CH="xoxoxoxoxoxoxoxo", OH="..x...x...x...x.", RS="....x.......x...")),
 ("D_alt",     S(BD="X...x...X...x...", CH="xoxoxoxoxoxoxoxo", MT="......o...o.....", LT="..........o...o.")),
 ("E_break",   S(CH="xoxoxoxoxoxoxoxo", HC="....X.......X...", MT="......o...o.....")),
 ("F_peak",    S(BD="X...x..xX...x..x", CH="xoxoxoxoxoxoxoxo", OH="..x...x...x...x.", HC="....X.......X...", CC="X...............")),
 ("G_fill",    S(BD="X...x...X.......", LT="........o.o.....", MT="............o.o.", HT="..............oX", CC="X...............")),
 ("H_outro",   S(BD="X...x...X...x...", RC="..o...o...o...o.")),
]),

"techno_detroit": dict(bpm=130, swing=0.12, patterns=[
 ("A_intro",   S(BD="X...x...X...x...", RC="..o...o...o...o.")),
 ("B_main",    S(BD="X...x...X...x...", CH="x.o.x.o.x.o.x.o.", HC="....X.......X...")),
 ("C_variant", S(BD="X...x...X...x...", CH="xoxoxoxoxoxoxoxo", HC="....X.......X...", RS="......o.......o.")),
 ("D_alt",     S(BD="X...x...X...x...", OH="..x...x...x...x.", RC="x.o.x.o.x.o.x.o.", MT="..........o.....")),
 ("E_break",   S(CH="x.o.x.o.x.o.x.o.", HC="....X.......X...", RC="x...x...x...x...")),
 ("F_peak",    S(BD="X...x...X...x...", CH="xoxoxoxoxoxoxoxo", OH="..x...x...x...x.", HC="....X.......X...")),
 ("G_fill",    S(BD="X...x...X.......", HC="....X...X.X.....", LT="..........o.o...", MT="..............o.")),
 ("H_outro",   S(BD="X...x...X...x...", RC="..o...o...o...o.")),
]),

# ------------------------------------------------------------------ DRUM & BASS

"dnb_liquid": dict(bpm=174, swing=0.0, patterns=[
 ("A_intro",   S(BD="X.......X.......", SD="....X.......X...", CH="..x...x...x...x.")),
 ("B_main",    S(BD="X.........X.....", SD="....X.......X...", CH="x.o.x.o.x.o.x.o.", RC="..x...x...x...x.")),
 ("C_variant", S(BD="X.........X.....", SD="....X..o....X...", CH="x.o.x.o.x.o.x.o.", RS="......o.......o.")),
 ("D_alt",     S(BD="X.....X...X.....", SD="....X.......X..o", CH="xoxoxoxoxoxoxoxo", RC="..o...o...o...o.")),
 ("E_break",   S(SD="....X.......X...", CH="xoxoxoxoxoxoxoxo", RC="x...x...x...x...")),
 ("F_peak",    S(BD="X.........X.....", SD="....X.......X...", CH="xoxoxoxoxoxoxoxo", OH="..............x.", CC="X...............")),
 ("G_fill",    S(BD="X.......X.......", SD="....X...o.o.o.o.", LT="............o...", MT="..............o.", HT="...............X")),
 ("H_outro",   S(BD="X.........X.....", SD="....X.......X...", RC="..o...o...o...o.")),
]),

"dnb_neuro": dict(bpm=174, swing=0.0, patterns=[
 ("A_intro",   S(BD="X.......X.......", SD="....X.......X...", CH="x.x.x.x.x.x.x.x.")),
 ("B_main",    S(BD="X....X....X.....", SD="....X.......X...", CH="xoxoxoxoxoxoxoxo")),
 ("C_variant", S(BD="X....X....X....X", SD="....X..o....X..o", CH="xoxoxoxoxoxoxoxo")),
 ("D_alt",     S(BD="X..X..X...X..X..", SD="....X.......X...", CH="x.x.x.x.x.x.x.x.", RC="..o...o...o...o.")),
 ("E_break",   S(SD="....X..o....X..o", CH="xoxoxoxoxoxoxoxo", RC="x...x...x...x...")),
 ("F_peak",    S(BD="X..X..X...X..X.X", SD="....X.......X...", CH="xoxoxoxoxoxoxoxo", CC="X...............")),
 ("G_fill",    S(BD="X.......X.......", SD="....X...X.o.X.o.", LT="..........o.....", HT="..............XX")),
 ("H_outro",   S(BD="X....X....X.....", SD="....X.......X...", CH="x.x.x.x.x.x.x.x.")),
]),

"dnb_jumpup": dict(bpm=175, swing=0.0, patterns=[
 ("A_intro",   S(BD="X.......X.......", SD="....X.......X...", CH="..x...x...x...x.")),
 ("B_main",    S(BD="X.........X.....", SD="....X.......X...", CH="x.x.x.x.x.x.x.x.", OH="..............x.")),
 ("C_variant", S(BD="X.......X.X.....", SD="....X.......X...", CH="xoxoxoxoxoxoxoxo", OH="......x.......x.")),
 ("D_alt",     S(BD="X.........X...X.", SD="....X.......X...", CH="x.x.x.x.x.x.x.x.", RS="......o.......o.")),
 ("E_break",   S(SD="....X.......X...", CH="xoxoxoxoxoxoxoxo", OH="..x...x...x...x.")),
 ("F_peak",    S(BD="X.........X.....", SD="....X.......X...", CH="xoxoxoxoxoxoxoxo", OH="..............x.", CC="X...............")),
 ("G_fill",    S(BD="X.......X.......", SD="....X.....X.X.X.", MT="............o...", HT="..............oX")),
 ("H_outro",   S(BD="X.........X.....", SD="....X.......X...", CH="..x...x...x...x.")),
]),

"dnb_jungle": dict(bpm=172, swing=0.0, patterns=[
 ("A_intro",   S(BD="X.......X.......", SD="....X.......X...", RC="..o...o...o...o.")),
 ("B_main",    S(BD="X.....X...X.....", SD="....X..o.X..X..o", CH="x.x.x.x.x.x.x.x.")),
 ("C_variant", S(BD="X.....X...X...X.", SD="....X..o.X..X..o", CH="xoxoxoxoxoxoxoxo", OH="..............x.")),
 ("D_alt",     S(BD="X...X.....X.....", SD="..o.X..o....X..o", CH="x.o.x.o.x.o.x.o.", RC="..x...x...x...x.")),
 ("E_break",   S(SD="....X..o.X..X..o", CH="xoxoxoxoxoxoxoxo", RC="x...x...x...x...")),
 ("F_peak",    S(BD="X.....X...X...X.", SD="....X..o.X..X..o", CH="xoxoxoxoxoxoxoxo", CC="X...............")),
 ("G_fill",    S(BD="X.......X.......", SD="....X..o.X.oX.oX", LT="..........o.....", MT="............o...", HT="..............oX")),
 ("H_outro",   S(BD="X.....X...X.....", SD="....X.......X...", RC="..o...o...o...o.")),
]),

"dnb_halftime": dict(bpm=172, swing=0.0, patterns=[
 ("A_intro",   S(BD="X...............", SD="........X.......", CH="..x...x...x...x.")),
 ("B_main",    S(BD="X.......X.......", SD="........X.......", CH="x.o.x.o.x.o.x.o.", RC="..x...x...x...x.")),
 ("C_variant", S(BD="X.....X.X.......", SD="........X.......", CH="xoxoxoxoxoxoxoxo", RS="..o...o...o...o.")),
 ("D_alt",     S(BD="X.......X...X...", SD="........X......o", CH="x.o.x.o.x.o.x.o.", OH="......x.......x.")),
 ("E_break",   S(SD="........X.......", CH="xoxoxoxoxoxoxoxo", RC="x...x...x...x...")),
 ("F_peak",    S(BD="X.....X.X.......", SD="........X.......", CH="xoxoxoxoxoxoxoxo", CC="X...............")),
 ("G_fill",    S(BD="X.......X.......", SD="........X.o.X.o.", LT="..........o.....", HT="..............oX")),
 ("H_outro",   S(BD="X.......X.......", SD="........X.......", RC="..o...o...o...o.")),
]),

"dnb_rollers": dict(bpm=174, swing=0.0, patterns=[
 ("A_intro",   S(BD="X.........X.....", CH="..x...x...x...x.")),
 ("B_main",    S(BD="X.........X.....", SD="....X.......X...", CH="xoxoxoxoxoxoxoxo")),
 ("C_variant", S(BD="X.........X.....", SD="....X..o....X..o", CH="xoxoxoxoxoxoxoxo", RC="..o...o...o...o.")),
 ("D_alt",     S(BD="X.......X.X.....", SD="....X.......X...", CH="xoxoxoxoxoxoxoxo", OH="..............x.")),
 ("E_break",   S(SD="....X.......X...", CH="xoxoxoxoxoxoxoxo", RC="x...x...x...x...")),
 ("F_peak",    S(BD="X.........X.....", SD="....X.......X...", CH="xoxoxoxoxoxoxoxo", OH="......x.......x.", CC="X...............")),
 ("G_fill",    S(BD="X.......X.......", SD="....X...o.o.X.o.", MT="............o...", HT="..............oX")),
 ("H_outro",   S(BD="X.........X.....", SD="....X.......X...", CH="..o...o...o...o.")),
]),

# ------------------------------------------------------------------ HOUSE

"house_deep": dict(bpm=122, swing=0.20, patterns=[
 ("A_intro",   S(BD="X...x...X...x...", CH="..x...x...x...x.")),
 ("B_main",    S(BD="X...x...X...x...", OH="..x...x...x...x.", CH="x.o.x.o.x.o.x.o.", HC="....X.......X...")),
 ("C_variant", S(BD="X...x...X...x...", OH="..x...x...x...x.", CH="xoxoxoxoxoxoxoxo", RS="......o.......o.")),
 ("D_alt",     S(BD="X...x...X...x...", OH="..x...x...x...x.", CH="x...x...x...x...", LT="..........o.....", RS="....o.......o...")),
 ("E_break",   S(OH="..x...x...x...x.", CH="xoxoxoxoxoxoxoxo", HC="....X.......X...", RC="x...x...x...x...")),
 ("F_peak",    S(BD="X...x...X...x...", OH="..x...x...x...x.", CH="xoxoxoxoxoxoxoxo", HC="....X.......X...", CC="X...............")),
 ("G_fill",    S(BD="X...x...X.......", CH="x.x.x.x.........", HC="....X...X.X.X.X.", CC="X...............")),
 ("H_outro",   S(BD="X...x...X...x...", CH="..o...o...o...o.", RC="x.......x.......")),
]),

"house_tech": dict(bpm=126, swing=0.10, patterns=[
 ("A_intro",   S(BD="X...x...X...x...", CH="..x...x...x...x.")),
 ("B_main",    S(BD="X...x...X...x...", CH="xoxoxoxoxoxoxoxo", OH="..x...x...x...x.", RS="....x.......x...")),
 ("C_variant", S(BD="X...x...X...x...", CH="xoxoxoxoxoxoxoxo", OH="..x...x...x...x.", HC="....X.......X...")),
 ("D_alt",     S(BD="X...x...X...x..x", CH="x.o.x.o.x.o.x.o.", OH="..x...x...x...x.", MT="......o...o.....")),
 ("E_break",   S(CH="xoxoxoxoxoxoxoxo", OH="..x...x...x...x.", HC="....X.......X...")),
 ("F_peak",    S(BD="X...X...X...X...", CH="xoxoxoxoxoxoxoxo", OH="..x...x...x...x.", HC="....X.......X...", CC="X...............")),
 ("G_fill",    S(BD="X...x...X.......", CH="x.x.x.x.........", LT="........o.o.....", MT="............o.o.", HT="..............oX")),
 ("H_outro",   S(BD="X...x...X...x...", CH="..o...o...o...o.")),
]),

"house_garage": dict(bpm=132, swing=0.50, patterns=[
 ("A_intro",   S(BD="X...............", SD="....X.......X...", CH="..x...x...x...x.")),
 ("B_main",    S(BD="X.......X.X.....", SD="....X.......X...", CH="x.o.x.o.x.o.x.o.", OH="..x...x...x...x.")),
 ("C_variant", S(BD="X.....X.X.X.....", SD="....X.......X..o", CH="xoxoxoxoxoxoxoxo", RS="......o.......o.")),
 ("D_alt",     S(BD="X.......X.X...X.", SD="....X..o....X...", CH="x.o.x.o.x.o.x.o.", OH="......x.......x.")),
 ("E_break",   S(SD="....X.......X...", CH="xoxoxoxoxoxoxoxo", OH="..x...x...x...x.", RC="x...x...x...x...")),
 ("F_peak",    S(BD="X.....X.X.X...X.", SD="....X.......X...", CH="xoxoxoxoxoxoxoxo", OH="..x...x...x...x.", CC="X...............")),
 ("G_fill",    S(BD="X.......X.......", SD="....X.....o.X.o.", MT="............o...", HT="..............oX")),
 ("H_outro",   S(BD="X.......X.X.....", SD="....X.......X...", CH="..o...o...o...o.")),
]),

"house_disco": dict(bpm=120, swing=0.15, patterns=[
 ("A_intro",   S(BD="X...x...X...x...", OH="..x...x...x...x.")),
 ("B_main",    S(BD="X...x...X...x...", OH="..x...x...x...x.", CH="x.x.x.x.x.x.x.x.", HC="....X.......X...")),
 ("C_variant", S(BD="X...x...X...x...", OH="..x...x...x...x.", CH="xoxoxoxoxoxoxoxo", RS="..o...o...o...o.")),
 ("D_alt",     S(BD="X...x...X...x...", OH="..x...x...x...x.", CH="x.x.x.x.x.x.x.x.", MT="......o...o.....", LT="..........o...o.")),
 ("E_break",   S(OH="..x...x...x...x.", CH="xoxoxoxoxoxoxoxo", HC="....X.......X...", RC="x...x...x...x...")),
 ("F_peak",    S(BD="X...x...X...x...", OH="..x...x...x...x.", CH="xoxoxoxoxoxoxoxo", HC="....X.......X...", CC="X...............")),
 ("G_fill",    S(BD="X...x...X.......", HC="....X...X.X.X.X.", LT="..........o.o...", MT="..............o.")),
 ("H_outro",   S(BD="X...x...X...x...", OH="..x...x...x...x.")),
]),

"house_afro": dict(bpm=124, swing=0.22, patterns=[
 ("A_intro",   S(BD="X...x...X...x...", RS="..o.o.....o.o...")),
 ("B_main",    S(BD="X...x...X...x...", CH="x.o.x.o.x.o.x.o.", MT="..o...o...o...o.", LT="......o.......o.")),
 ("C_variant", S(BD="X...x...X...x...", CH="xoxoxoxoxoxoxoxo", MT="..o.o...o.o.o...", LT="....o...o...o.o.")),
 ("D_alt",     S(BD="X...x...X...x...", OH="..x...x...x...x.", MT="..o...o...o...o.", HT="......o.......o.", RS="....o.......o...")),
 ("E_break",   S(CH="xoxoxoxoxoxoxoxo", MT="..o.o...o.o.o...", LT="....o...o...o.o.", RC="x...x...x...x...")),
 ("F_peak",    S(BD="X...x...X...x...", CH="xoxoxoxoxoxoxoxo", OH="..x...x...x...x.", MT="..o...o...o...o.", CC="X...............")),
 ("G_fill",    S(BD="X...x...X.......", LT="........o.o.o...", MT="............o.o.", HT="..............oX")),
 ("H_outro",   S(BD="X...x...X...x...", MT="..o...o...o...o.")),
]),

"house_jackin": dict(bpm=125, swing=0.30, patterns=[
 ("A_intro",   S(BD="X...x...X...x...", CH="..x...x...x...x.")),
 ("B_main",    S(BD="X...x...X...x...", CH="x.o.x.o.x.o.x.o.", HC="....X.......X...", RS="......o.......o.")),
 ("C_variant", S(BD="X...x..xX...x...", CH="xoxoxoxoxoxoxoxo", HC="....X.......X...", OH="..x...x...x...x.")),
 ("D_alt",     S(BD="X...x...X...x...", OH="..x...x...x...x.", CH="x.o.x.o.x.o.x.o.", MT="..........o.....")),
 ("E_break",   S(CH="xoxoxoxoxoxoxoxo", HC="....X.......X...", RC="x...x...x...x...")),
 ("F_peak",    S(BD="X...x..xX...x..x", CH="xoxoxoxoxoxoxoxo", OH="..x...x...x...x.", HC="....X.......X...", CC="X...............")),
 ("G_fill",    S(BD="X...x...X.......", HC="....X...X.X.X.X.", LT="..........o.o...", HT="..............oX")),
 ("H_outro",   S(BD="X...x...X...x...", CH="..o...o...o...o.")),
]),

"house_french": dict(bpm=123, swing=0.18, patterns=[
 ("A_intro",   S(BD="X...x...X...x...", OH="..x...x...x...x.")),
 ("B_main",    S(BD="X...x...X...x...", OH="..x...x...x...x.", CH="x.x.x.x.x.x.x.x.", HC="....X.......X...")),
 ("C_variant", S(BD="X...x...X...x...", OH="..x...x...x...x.", CH="xoxoxoxoxoxoxoxo", HC="....X.......X...", RS="......o.......o.")),
 ("D_alt",     S(BD="X...x...X...x...", OH="..x...x...x...x.", CH="x.o.x.o.x.o.x.o.", RC="....x.......x...")),
 ("E_break",   S(OH="..x...x...x...x.", CH="xoxoxoxoxoxoxoxo", HC="....X.......X...")),
 ("F_peak",    S(BD="X...X...X...X...", OH="..x...x...x...x.", CH="xoxoxoxoxoxoxoxo", HC="....X.......X...", CC="X...............")),
 ("G_fill",    S(BD="X...x...X.......", CH="x.x.x.x.........", HC="....X...X.X.X.X.", CC="X...............")),
 ("H_outro",   S(BD="X...x...X...x...", OH="..x...x...x...x.")),
]),

# ------------------------------------------------------------------ LO-FI / HIP HOP

"lofi_boombap": dict(bpm=88, swing=0.38, patterns=[
 ("A_intro",   S(BD="X.......X.......", CH="x...x...x...x...")),
 ("B_main",    S(BD="X.....X.o.......", SD="....X.......X...", CH="x.o.x.o.x.o.x.o.")),
 ("C_variant", S(BD="X.....X...X.....", SD="....X.......X..o", CH="x.o.x.o.x.o.x.o.", RS="..o...........o.")),
 ("D_alt",     S(BD="X.......X.....X.", SD="....X.......X...", CH="x.oox.oox.oox.oo", RC="..o.......o.....")),
 ("E_break",   S(SD="....o.......o...", CH="x.o.x.o.x.o.x.o.", RC="x.......x.......")),
 ("F_peak",    S(BD="X.....X.o.X.....", SD="....X.......X...", CH="x.o.x.o.x.o.x.o.", OH="..............x.")),
 ("G_fill",    S(BD="X.......X.......", SD="....X.....o.o.o.", LT="..........o.....", MT="............o...", HT="..............o.")),
 ("H_outro",   S(BD="X.......X.......", CH="x...x...x...x...")),
]),

"lofi_chillhop": dict(bpm=78, swing=0.42, patterns=[
 ("A_intro",   S(BD="X.......X.......", RC="..o...o...o...o.")),
 ("B_main",    S(BD="X.......X.......", SD="....X.......X...", CH="x.o.x.o.x.o.x.o.")),
 ("C_variant", S(BD="X.....X.X.......", SD="....X.......X...", CH="x.oox.oox.oox.oo", RS="......o.......o.")),
 ("D_alt",     S(BD="X.......X.....X.", SD="....X......oX...", CH="x.o.x.o.x.o.x.o.", RC="..o.......o.....")),
 ("E_break",   S(SD="....o.......o...", CH="x.o.x.o.x.o.x.o.", RC="x.......x.......")),
 ("F_peak",    S(BD="X.....X.X.......", SD="....X.......X...", CH="x.oox.oox.oox.oo", OH="..............x.")),
 ("G_fill",    S(BD="X.......X.......", SD="....X.......o.o.", MT="..........o.....", HT="..............o.")),
 ("H_outro",   S(BD="X.......X.......", RC="..o...o...o...o.")),
]),

"lofi_dusty": dict(bpm=72, swing=0.45, patterns=[
 ("A_intro",   S(BD="X.......X.......", CH="x...x...x...x...")),
 ("B_main",    S(BD="X.....X.........", SD="....X.......X...", CH="x.o.x.o.x.o.x.o.", RS="..o...........o.")),
 ("C_variant", S(BD="X.....X...X.....", SD="....X..o....X..o", CH="x.oox.oox.oox.oo")),
 ("D_alt",     S(BD="X.......X.......", SD="....X.......X...", CH="x.o.x.o.x.o.x.o.", LT="..........o.....", RC="..o.......o.....")),
 ("E_break",   S(SD="....o.......o...", CH="x.o.x.o.x.o.x.o.", RC="x.......x.......")),
 ("F_peak",    S(BD="X.....X...X.....", SD="....X.......X...", CH="x.oox.oox.oox.oo", OH="..............x.")),
 ("G_fill",    S(BD="X.......X.......", SD="....X.....o.o.o.", LT="..........o.....", MT="............o...")),
 ("H_outro",   S(BD="X.......X.......", CH="x...x...x...x...")),
]),

"lofi_triphop": dict(bpm=90, swing=0.30, patterns=[
 ("A_intro",   S(BD="X.......X.......", RC="..o...o...o...o.")),
 ("B_main",    S(BD="X.....X.X.......", SD="....X.......X...", CH="x.o.x.o.x.o.x.o.")),
 ("C_variant", S(BD="X.....X.X.....X.", SD="....X.......X..o", CH="xoxoxoxoxoxoxoxo", RS="......o.......o.")),
 ("D_alt",     S(BD="X.......X.......", SD="....X.......X...", OH="..x...x...x...x.", CH="x...x...x...x...", LT="..........o.....")),
 ("E_break",   S(SD="....X.......X...", CH="x.o.x.o.x.o.x.o.", RC="x...x...x...x...")),
 ("F_peak",    S(BD="X.....X.X.....X.", SD="....X.......X...", CH="xoxoxoxoxoxoxoxo", OH="..............x.", CC="X...............")),
 ("G_fill",    S(BD="X.......X.......", SD="....X.....o.X.o.", MT="..........o.....", HT="..............o.")),
 ("H_outro",   S(BD="X.......X.......", RC="..o...o...o...o.")),
]),

"lofi_lounge": dict(bpm=84, swing=0.40, patterns=[
 ("A_intro",   S(BD="X.......X.......", RC="x.o.x.o.x.o.x.o.")),
 ("B_main",    S(BD="X.......X.......", SD="....X.......X...", RC="x.o.x.o.x.o.x.o.", RS="......o.......o.")),
 ("C_variant", S(BD="X.....X.X.......", SD="....X.......X..o", RC="x.oox.oox.oox.oo")),
 ("D_alt",     S(BD="X.......X.......", SD="....X.......X...", CH="x.o.x.o.x.o.x.o.", MT="..........o.....")),
 ("E_break",   S(SD="....o.......o...", RC="x.o.x.o.x.o.x.o.")),
 ("F_peak",    S(BD="X.....X.X.......", SD="....X.......X...", CH="x.oox.oox.oox.oo", OH="..............x.")),
 ("G_fill",    S(BD="X.......X.......", SD="....X.......o.o.", LT="..........o.....", MT="............o...")),
 ("H_outro",   S(BD="X.......X.......", RC="x.o.x.o.x.o.x.o.")),
]),

# ------------------------------------------------------------------ OTHER

"breakbeat": dict(bpm=132, swing=0.0, patterns=[
 ("A_intro",   S(BD="X.......X.......", SD="....X.......X...", CH="..x...x...x...x.")),
 ("B_main",    S(BD="X.....X...X.....", SD="....X.......X...", CH="x.x.x.x.x.x.x.x.")),
 ("C_variant", S(BD="X.....X...X...X.", SD="....X..o....X..o", CH="xoxoxoxoxoxoxoxo", OH="..............x.")),
 ("D_alt",     S(BD="X...X.....X.....", SD="..o.X.......X..o", CH="x.o.x.o.x.o.x.o.", RC="..x...x...x...x.")),
 ("E_break",   S(SD="....X..o....X..o", CH="xoxoxoxoxoxoxoxo", RC="x...x...x...x...")),
 ("F_peak",    S(BD="X.....X...X...X.", SD="....X.......X...", CH="xoxoxoxoxoxoxoxo", CC="X...............")),
 ("G_fill",    S(BD="X.......X.......", SD="....X...o.o.X.o.", LT="..........o.....", MT="............o...", HT="..............oX")),
 ("H_outro",   S(BD="X.....X...X.....", SD="....X.......X...", CH="..o...o...o...o.")),
]),

"electro": dict(bpm=128, swing=0.0, patterns=[
 ("A_intro",   S(BD="X.......X.......", CH="..x...x...x...x.")),
 ("B_main",    S(BD="X..X....X..X....", SD="....X.......X...", CH="x.x.x.x.x.x.x.x.")),
 ("C_variant", S(BD="X..X..X.X..X....", SD="....X.......X...", CH="xoxoxoxoxoxoxoxo", RS="......o.......o.")),
 ("D_alt",     S(BD="X..X....X..X..X.", SD="....X.......X...", OH="..x...x...x...x.", CH="x...x...x...x...")),
 ("E_break",   S(SD="....X.......X...", CH="xoxoxoxoxoxoxoxo", HC="....X.......X...")),
 ("F_peak",    S(BD="X..X..X.X..X..X.", SD="....X.......X...", CH="xoxoxoxoxoxoxoxo", CC="X...............")),
 ("G_fill",    S(BD="X..X....X.......", SD="....X.....X.X.X.", LT="..........o.....", HT="..............oX")),
 ("H_outro",   S(BD="X..X....X..X....", CH="..o...o...o...o.")),
]),

"dubstep": dict(bpm=140, swing=0.0, patterns=[
 ("A_intro",   S(BD="X...............", SD="........X.......", CH="..x...x...x...x.")),
 ("B_main",    S(BD="X.......X.......", SD="........X.......", CH="x.o.x.o.x.o.x.o.")),
 ("C_variant", S(BD="X.....X.X.......", SD="........X.......", CH="xoxoxoxoxoxoxoxo", RS="..o...o...o...o.")),
 ("D_alt",     S(BD="X.......X...X...", SD="........X......o", OH="..x...x...x...x.", CH="x...x...x...x...")),
 ("E_break",   S(SD="........X.......", CH="xoxoxoxoxoxoxoxo", RC="x...x...x...x...")),
 ("F_peak",    S(BD="X.....X.X.......", SD="........X.......", CH="xoxoxoxoxoxoxoxo", CC="X...............")),
 ("G_fill",    S(BD="X.......X.......", SD="........X.o.X.o.", LT="..........o.....", HT="..............oX")),
 ("H_outro",   S(BD="X.......X.......", SD="........X.......", RC="..o...o...o...o.")),
]),

"downtempo": dict(bpm=100, swing=0.25, patterns=[
 ("A_intro",   S(BD="X.......X.......", RC="..o...o...o...o.")),
 ("B_main",    S(BD="X.......X.......", SD="....X.......X...", CH="x.o.x.o.x.o.x.o.", RS="......o.......o.")),
 ("C_variant", S(BD="X.....X.X.......", SD="....X.......X...", CH="xoxoxoxoxoxoxoxo", MT="..........o.....")),
 ("D_alt",     S(BD="X.......X.....X.", SD="....X.......X...", OH="..x...x...x...x.", CH="x...x...x...x...")),
 ("E_break",   S(SD="....o.......o...", CH="x.o.x.o.x.o.x.o.", RC="x...x...x...x...")),
 ("F_peak",    S(BD="X.....X.X.......", SD="....X.......X...", CH="xoxoxoxoxoxoxoxo", OH="..............x.")),
 ("G_fill",    S(BD="X.......X.......", SD="....X.......o.o.", LT="..........o.....", MT="............o...", HT="..............o.")),
 ("H_outro",   S(BD="X.......X.......", RC="..o...o...o...o.")),
]),

"ambient_perc": dict(bpm=110, swing=0.15, patterns=[
 ("A_intro",   S(RC="x.......x.......")),
 ("B_main",    S(BD="X.......X.......", RC="x...o...x...o...", RS="......o.......o.")),
 ("C_variant", S(BD="X.......X.......", RC="x.o.x.o.x.o.x.o.", MT="..o.......o.....", LT="......o.......o.")),
 ("D_alt",     S(BD="X.....X.X.......", OH="..x...x...x...x.", RS="....o.......o...", MT="..........o.....")),
 ("E_break",   S(RC="x.o.x.o.x.o.x.o.", MT="..o.......o.....", LT="......o.......o.")),
 ("F_peak",    S(BD="X.......X.......", CH="x.o.x.o.x.o.x.o.", OH="..x...x...x...x.", MT="..o...o...o...o.")),
 ("G_fill",    S(BD="X.......X.......", LT="........o.o.....", MT="............o...", HT="..............o.")),
 ("H_outro",   S(RC="x.......x.......")),
]),

}


def validate():
    """Every step string must be exactly 16 characters of the legal alphabet."""
    legal = set("Xxo.")
    errs = []
    for style, spec in STYLES.items():
        if len(spec["patterns"]) != 8:
            errs.append(f"{style}: {len(spec['patterns'])} variations, expected 8")
        for vname, tracks in spec["patterns"]:
            for tname, s in tracks.items():
                if len(s) != 16:
                    errs.append(f"{style}/{vname}/{tname}: length {len(s)}, expected 16")
                bad = set(s) - legal
                if bad:
                    errs.append(f"{style}/{vname}/{tname}: illegal chars {bad}")
    return errs


if __name__ == "__main__":
    errs = validate()
    hits = sum(sum(sum(1 for c in s if c in "Xxo")
                   for s in tracks.values())
               for spec in STYLES.values()
               for _, tracks in spec["patterns"])
    print(f"{len(STYLES)} styles, {len(STYLES)*8} variations, {hits} total hits")
    if errs:
        print(f"\n{len(errs)} PROBLEMS:")
        for e in errs:
            print("  " + e)
    else:
        print("all step strings valid (16 chars, legal alphabet)")
