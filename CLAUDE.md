# Tokoya — Project Working Notes

This file is a handoff log for Claude Code sessions.
**Read this first** before touching anything in this repo.

## v0.6.3 Settle evaluated-coordinate fix (2026-07-07)

Root cause of scalp penetration after `Settle Hair Back`: `_initial_groom.py`
was solving in raw Curves object coordinates while the visible hair used the
evaluated Surface Deform result. In the measured scene, raw and evaluated
positions differed by about 27.5 mm on average and up to about 39.8 mm, so a
raw-space collision pass could still display inside the scalp.

Fix: read both raw and evaluated Curves positions, solve the initial groom in
evaluated world space, then write back `target_eval_world - eval_offset` so the
modifier reconstructs the solved visible positions. This mirrors the established
offset-compensation pattern in `_world_passthrough.py` and `_mesh_ops.py`.

Known limitation: small residual issues around the ears are expected from the
filled Body collider proxy. The proxy intentionally removes ear protrusion faces
before filling holes so closed-inside parity checks remain stable; therefore its
ear-area collision shape does not exactly match the visible Body mesh.

---

## v0.6.2 Settle migration note (2026-07-05, superseded)

The old `tokoya.simulate` button was replaced with `Settle Hair Back`, and Hair,
Body, Clothes, and Cutter pickers were added. The old detailed migration note
has been intentionally removed because it encouraged future debugging to trust
the migration path instead of re-auditing coordinate spaces.

Use the v0.6.3 note above as authoritative for Settle behavior: collision and
grooming decisions must match the visible evaluated Curves coordinates.

---

## v0.6.1 final Simulate length fix (2026-06-29)

Root cause of the "hair gets longer after Simulate": the final safety audit in
`_world_passthrough.run_simulation()` resolved residual segment/body crossings by
snapping individual downstream points to the Body surface, then wrote the result
back without another length reconciliation. That collision-only direct correction
can increase strand arc length even though the XPBD spring solve itself uses rest
segment lengths.

Fix: capture per-segment lengths from the pre-sim world positions, and after each
final cleanup pass rebuild each strand from root to tip using the current
directions but the original segment lengths. Points 0 and 1 remain follicle
anchors. Protected/frozen strands are skipped. This keeps the final Body cleanup
from becoming an accidental hair-length edit.

---

## Tokoya v0.5.0 (2026-06-21)

- v0.5.xはヘアーモデリング改善系列。大々的な公開pushは保留。
- GravityをXYZベクトル化。既定値`(0, 0, -9.81)`。
- 長い髪の初期整髪時に`+Y`重力を一時指定し、後方へ誘導可能。
- 旧Substeps UIを廃止。物理Substepsは内部で1固定。
- 旧Substeps位置へ`Interpolation Mag`を追加。既定1、範囲1～16。
- Autoまたは手動Frame InterpolationへInterpolation Magを乗算する。
- v0.4.8の固定2倍を廃止。Auto基礎値はv0.4.7相当へ戻す。
- Iterations既定値を20から10へ変更。
- REC用物理パラメーターはREC ON時に`_snapshot_sim_params()`で読み込む。
  Gravityなどを区間途中で変える場合はREC OFF→設定変更→REC ONで反映する。
  斜め後方へ引く区間と、下へ垂らす区間を分ける運用が可能。
- Interpolation Magは録画中も各フレームでWM値を読むため、次フレームから反映。

---

## Tokoya v0.4.8 (2026-06-21)

- Auto Frame Interpolationが少し粗かったため、自動ステップ数を2倍化。
- 旧Auto式の算出結果を2倍する。実質的な目標移動量は約12.5%。
- Auto上限を32から64へ変更。静止時は引き続き1。
- 実シーン422→423相当のAuto計算は15から30へ増加。

---

## Tokoya v0.4.7 (2026-06-21)

- 録画中のWarp CUDA位置・速度をGPU上に保持し、Frame Interpolation間の
  CPU→GPU再アップロードを廃止。位置は表示用、速度はフレーム確定時だけ取得。
- `Auto Frame Interpolation`を追加し、既定ON。
- REC開始時に毛根最近傍間隔の中央値を測定。各フレームの最大毛根移動から
  `ceil(max_move * 1.1 / (median_spacing * 0.25))`を計算し、1～32へ制限。
- 手動Frame InterpolationはAuto OFF時に使用。
- Substeps既定値を8から1へ変更。機能とUIは維持。
- 実シーン421～424で、頭頂部の422→423移動は平均5.091 mm、最大5.704 mm。
  毛根間隔中央値1.768 mm。Auto計算は15となり、実測で安定した14に近い。
- CPU/CUDA録画スモーク、Auto数式、Substeps既定値を検証。

---

## ⚠️ START HERE — Tokoya v0.4.4 (2026-06-20)

### プロジェクト休止スナップショット

- Tokoya v0.4.4を現在の安定版として、当面の開発を終了する。
- 配布ZIP: `dist/tokoya-0.4.4.zip`
- SHA256:
  `BF02757A0206AAD75AC7D2EED5AA94676A226FD474315C28AB28C4A03EF0619E`
- 本番実測はGPU共有化前の80フレーム/分から120フレーム/分へ向上。
  総処理速度は1.5倍。
- CUDA時はXPBD物理とWarp Body衝突が同じGPU配列を共有する。
  CPU/VulkanおよびWarp失敗時のフォールバックは維持。
- 初期設定はBending OFF、Stiffness 9.0、Damping 8.0、Mass 100。
- Collision Proxyは複数方式を実機検証したが、本番速度が
  120フレーム/分のまま変化しなかったため不採用。下記記録を参照。
- 今後はバグが見つかった場合にのみ再開する。再開時はまず再現条件を固定し、
  v0.4.4との差分を最小化して修正する。
- 効果を実測できない最適化や、シミュレーション品質を変える変更は
  推測だけで採用しない。

### Collision Proxy実験記録 — 不採用・削除済み

- 目的: 449,472三角形の`CC_Base_Body`を軽量な衝突対象へ置き換え、
  v0.4.4の実測120フレーム/分をさらに高速化できるか検証した。
- `Body Mesh`と任意の`Collision Mesh`を分離し、未指定時はBodyへ
  フォールバックするUIと実装を試作した。
- 単純Decimate:
  30,000三角形では物理部分が約3.4倍になったが、元Body基準で
  1,263セグメント交差が発生。粗い三角面による偽衝突もあり不採用。
- Un-Subdivide:
  112,368三角形まで削減できたが、元Body基準で313交差が残り不採用。
  外側オフセットやShrinkwrapも、近接面への誤投影と大きな位置差が発生。
- 安全な上半身切り出し:
  Hair最下点から20 cm下より上の元Body面をそのまま複製し、
  Arm/Hand/Shoulder/Clavicle/Finger系マテリアル・ウェイトを保護した。
  Shape Keys 189個、ドライバー2個、ARKit Action、Armature、
  78ウェイトグループを維持。元Bodyは変更しない方式。
- 上半身方式は449,472→350,328三角形。元Bodyとプロキシの残留交差は
  ともに1、平均位置差0.00013 mm、最大0.271 mmで品質は一致した。
- しかし本番実測はプロキシなし・ありともに120フレーム/分で変化なし。
  三角形削減率約22%では、Blender評価・Mesh生成・その他処理を含む
  総時間を改善できなかった。
- 結論:
  速度向上がなく、Collision指定、Shape Key同期、腕保護、生成UIなどの
  複雑さだけが増えるため、実装・テスト・v0.4.5 ZIPをすべて破棄した。
  公開版はv0.4.4へ戻した。
- 将来再検討する条件:
  衝突範囲を大幅に削減してもアニメーション全体で安全と証明できる、
  またはBody Mesh評価/BVH構築が再び主要ボトルネックになった場合のみ。
  単純Decimate案は同じ品質問題を再発するため繰り返さない。

### v0.4.4 Warp GPU共有化

- CUDA時のXPBD物理をWarpへ移し、Body衝突と同じGPU配列を直接共有する。
- サブステップ内のTaichi→NumPy→Warp→NumPy→Taichi往復を除去。
- 36,000点の物理＋衝突ベンチは0.148秒→0.054秒、約2.75倍。
- ユーザー本番実測は1分80フレーム→120フレーム。
- 初期設定をBending OFF、Stiffness 9.0、Damping 8.0、Mass 100へ変更。
- CUDA/CPU録画、登録ロールバック、Bending ON/OFF数値比較を通過。
- 配布ZIP: `dist/tokoya-0.4.4.zip`
- SHA256:
  `BF02757A0206AAD75AC7D2EED5AA94676A226FD474315C28AB28C4A03EF0619E`

### 電源断・次回セッション再開用スナップショット

- 最新コミット: `0fb1fe2 Tokoya v0.4.3: accelerate body collision with Warp CUDA`
- `origin/main`へpush済み。ローカル作業ツリーはpush直後クリーン。
- 配布ZIP: `dist/tokoya-0.4.3.zip`
- SHA256:
  `2CF0F436F6C5EAB54ECE42F8CE4C919D8934A67B785A3E666409FC6150B2582B`
- 本番Blend:
  `C:\Users\azoo\Documents\Blender\QueSera2\YOKO3-3-4test.blend`
- 本番録画キャッシュ:
  `YOKO3-3-4test.blend.tokoya-cache.npz`
- MCP監査時のHair:
  `Curves`、4,000本、9点/本、合計36,000点。
- Body: `CC_Base_Body`。評価後メッシュは約225,184頂点、
  449,472三角形（Blender loop triangle化後）。
- 本番設定:
  CUDA、Frame Interpolation=2、Physics Substeps=8、Iterations=20、
  FPS=24、FPS Base=1。
- ユーザー実測:
  80フレームを約1分。Frame Interpolation=2なので小数フレーム物理計算は
  合計160回。約0.375秒/小数フレーム。
- 開発計測:
  旧v0.4.2は1フレーム19.85秒、うちPython BVH衝突19.00秒（95.7%）。
  v0.4.3定常値は1フレーム0.687秒、旧版比28.9倍。
- 4,000本の静的`Simulate`は1ステップ0.858秒。
- 全32,000ストランドセグメントの最終Body交差監査は0。
- v0.4.3の実装:
  `_collision_warp.py`でNVIDIA Warp 1.13.0のCUDA Mesh BVHを使用。
  点スイープCCD、近傍投影、セグメントレイ、内向き法線速度除去をGPU化。
- NVIDIA WarpはBlender 5.1に同梱されており、RTX 5070 Ti
  （16 GiB、sm_120）を正常認識。追加PyTorchインストールは不要。
- CUDAでWarpが失敗した場合、またはVulkan/CPUでは旧Python Blender BVHへ
  自動フォールバックする。
- 初回だけWarpカーネルコンパイルに約1秒。以後はWarpキャッシュを使用。
- v0.4.2で実装したREC仕様:
  REC→Timeline Play、順方向+1のみ録画、逆再生/ジャンプでPLAYBACKへ停止、
  再録画開始フレーム以降を上書き、位置+速度をNPZ保存。
- REC中は`scene.sync_mode = "NONE"`（Play Every Frame）へ自動変更し、
  停止時に元設定へ戻す。`Sync to Audio`のままだと計算中にフレームが飛び、
  録画がジャンプ判定で停止していた。
- Blender拡張登録時の`_RedirectData.filepath`問題はv0.4.1で修正済み。
  登録途中の例外はOperator/Panel/Property/handlerをロールバックする。
- テスト:
  `tests/recording_smoke.py`はCUDA/CPU、静的Simulate、REC、逆再生停止、
  再録画、NPZ保存・読込を検証。
  `tests/registration_rollback.py`は登録失敗後の再登録を検証。
  `tests/warp_collision_benchmark.py`はWarp Mesh近傍照会ベンチ。
- 注意:
  MCP上でワークスペース版を一時ロードして1062/1063をベンチしたが、
  本番インストール済みv0.4.2側の録画キャッシュは1061まで保存済み。
  ベンチ後、表示Hairは録画済み1061フレームへ復元した。
- 次回開始:
  1. Blender再起動。
  2. `dist/tokoya-0.4.3.zip`をインストール。
  3. 本番Blendを開き、Frame 1061付近からRECを再開。
  4. 見た目、Body貫通、録画キャッシュ保存を本番尺で確認。
- 現時点の次課題は、v0.4.3を本番アニメーション全体で視覚評価すること。
  速度目標「10倍」は達成済み。次は品質・安定性を優先する。

### v0.4.3 Warp CUDA衝突高速化

- 性能計測: 4,000本、36,000点、32,000セグメント、
  Frame Interpolation=2、Physics Substeps=8、Iterations=20。
- 旧RECは1フレーム19.85秒。そのうちPython/Blender BVH衝突が
  19.00秒（95.7%）、1フレーム96回呼び出されていた。
- NVIDIA Warp 1.13.0の`wp.Mesh`、`mesh_query_point_no_sign`、
  `mesh_query_ray`を使い、点CCD、近傍投影、セグメント交差、法線速度除去を
  RTX 5070 Ti上のCUDAカーネルへ移行。
- 実シーン定常値: REC 0.687秒/フレーム。旧版比28.9倍。
- Warp衝突コール96回相当は約0.091秒。全32,000セグメント貫通0。
- 静的`Simulate`も同じWarp経路を使用し、4,000本の1ステップが0.858秒。
- CUDAでWarpが利用できない場合、Vulkan/CPUの場合は旧Python BVHへ
  自動フォールバック。
- Warp初回カーネルコンパイルは約1秒。以後はWarpキャッシュを使用。
- `_collision_warp.py`を追加。CUDA Body Meshは評価済みワールド座標から
  三角形化し、各小数フレームでGPU Mesh BVHを構築する。

### v0.4.x タイムライン録画

- v0.3.5は最初の公開MIT版。v0.2.xはClaude Codeによる非公開開発。
- 既存の`Simulate`は現在フレームの静的整髪用として維持。
- `REC`トグルと`Frame Interpolation`を追加。
- 順方向へ1フレームずつ進む場合のみ録画し、逆再生・ジャンプは録画を中止。
- 録画停止後はPLAYBACKへ移行。未録画フレームではCurvesを変更しない。
- Blenderの`fps_base / fps`を実秒として使い、フレーム間を指定回数で評価。
- 各小数フレームで評価済みBody BVH、毛根、毛包方向を更新してCUDA計算。
- 再録画開始フレーム以降は上書き。
- 位置と速度をRAM保持し、`.blend`保存時に隣接する
  `<project>.blend.tokoya-cache.npz`へ圧縮保存。再読込時にPLAYBACK可能。
- v0.4.1: Blender拡張登録時の`_RedirectData`に`filepath`がない問題を修正。
  登録途中の例外ではOperator、Panel、WM Property、handlerをロールバックする。
- v0.4.2: `Sync to Audio`が重い計算中にフレームを飛ばし、ジャンプ判定で
  RECが停止する問題を修正。REC中だけ`scene.sync_mode = "NONE"`
  （Play Every Frame）へ変更し、停止時に元の設定へ戻す。
- Blender 5.1.2でCPU/CUDA、既存Simulate、録画、逆再生アボート、
  再録画上書き、保存・再読込、登録失敗ロールバックを自動試験済み。

MIT Licenseで公開。公開名`Tokoya`は日本語の「床屋」、英語の`barber`。
v0.3.5で静的スタイリングを初公開し、v0.4.xでCUDAタイムライン録画を追加。

**This repo**: `blender-tokoya-extension`
**Active branch**: `vbd-features-applied`（GitHub `origin/main`を追跡）
**Install zip**: `dist/tokoya-0.4.2.zip`
**N-panel tab**: "Tokoya"  
**Blender**: 5.1, Windows x64, RTX 5070 Ti (CUDA sm_120)

### このプロジェクトは何か

**床屋（Tokoya）**: Blender 5.1用ヘアースタイリング・アニメーション拡張。
UVマスク植毛、静的整髪、メッシュカット、CUDAアニメーション録画を提供する。

**Katsura との違い**:

| Katsura | Tokoya |
|---|---|
| 研究用の旧VBD/Warp構成 | Taichi XPBD、CUDA/Vulkan/CPU |
| 固定対象・旧8点ストランド | 選択Body、9点非等間隔ストランド |
| RAMベイク中心 | RAM録画＋圧縮外部キャッシュ |
| Start/Stop/Bypass | RECトグル＋自動PLAYBACK |
| リアルタイム志向 | 正確な逐次フレーム計算、非リアルタイム可 |

---

## アーキテクチャ (v0.4.2)

```
_sim_taichi.py        — Taichi XPBDソルバー、可変9点、動く毛根・毛包方向
_collision_warp.py    — Warp CUDA Body衝突バッチ処理
_world_passthrough.py — 現在フレームの静的SimulateとBody衝突
_recording.py         — REC/PLAYBACK、フレーム補間、RAM・NPZキャッシュ
_mask_plant.py        — UVグレースケールマスク植毛
_mesh_ops.py          — Mesh Shrink、Urchin Reset
__init__.py           — Operator、WM Property、persistent handler
ui.py                 — Tokoya N-パネル
tokoya_defaults.json  — 物理パラメーターデフォルト
blender_manifest.toml — 拡張manifestと配布対象
```

### WM プロパティ一覧

| プロパティ | 型 | 説明 |
|---|---|---|
| `tokoya_alpha` | Float | 植毛半径 α cm（Plant Hair用） |
| `tokoya_beta`  | Float | 植毛間隔 β cm（Plant Hair用） |
| `tokoya_n`     | Float | 長さcm（Extend）または反復回数（Simulate） |
| `tokoya_ref_obj` | String | 参照オブジェクト名（Empty or Mesh） |
| `tokoya_spring_ke` など | Float/Int/Bool | 物理パラメーター（Simulate時に適用） |

---

## 6ボタンの動作仕様

### 1. Plant Hair
- **入力**: Ref Obj (EMPTY) + α + β
- **処理**: `_spiral_plant.plant_hair(empty_obj, alpha_cm, beta_cm)`
- **前提**: シーンにCurvesオブジェクトが1個、`curves.surface = CC_Base_Body`、UV設定済み、CC_Base_Tongue02ボーン有り
- **テスト実績**: α=27cm β=0.3cm、エンプティ（日本語名）で動作確認 ✅

### 2. Extend
- **入力**: N cm
- **処理**: `_mesh_ops.extend_length(obj, target_m=N/100)`
- **動作**: 全ストランドをローカル座標でスケール（根元固定、先端をN cmに）
- **用途**: ウニ → 大きなウニ（長さ統一）

### 3. Simulate（v0.2.6 保護機能追加）
- **入力**: N（反復回数）、Ref Obj（オプション: 閉じたMESH）
- **処理**: `_snapshot_sim_params()` → `_world_passthrough.run_simulation(name, N, scene, protected_indices)`
- **物理**: Taichi XPBD、CC_Base_Body 固定コリジョン（常にON）
- **modifier補正**: eval_world - orig_world のオフセット補正あり（Katsura方式）
- **ルート固定**: point[0]と point[1] がキネマティック（毛包アンカー）
- **保護機能**: Ref Obj が閉じたMESHのとき、内側の毛根を持つストランドは全点凍結（重力・コリジョン無効）
  - 内側判定: ray counting（+Z方向レイキャスト、奇数交差＝内側）
  - 凍結方式: 各ステップ後に初期world座標へリストア＋速度ゼロ化
  - Ref Obj未設定/開いたメッシュ/MESHでない場合は従来通り全毛シミュレーション

### 4. Mesh Shrink
- **入力**: Ref Obj (MESH)
- **処理**: `_mesh_ops.mesh_shrink(obj, ref_mesh_obj)`
- **アルゴリズム**:
  1. evaluated world 座標を読む（Surface Deform modifier込み）
  2. 全セグメントを走査して BVH 双方向レイキャスト
  3. **全交差のうち最小弧長**を切断点とする（筒・球体の2重交差対応）
  4. scale = hit_arc / total_arc でローカル座標をスケール
- **用途例**: Plane=高さカット、UV Sphere=丸くカット、筒=筒状カット
- **注意**: CURVE タイプ（楕円、円）は不可。UV Sphere を潰して使うこと

### 5. Mesh Extend（v0.2.6 仕様変更）
- **入力**: Ref Obj (閉じたMESH) + N cm
- **処理**: `_mesh_ops.mesh_extend_protected(obj, ref_mesh_obj, target_m)`
- **アルゴリズム**:
  1. `_is_closed_mesh` でRef Objが閉じているか確認（開いていれば0を返す）
  2. 各ストランドの `point[0]`（world座標）が閉じたプリミティブの内側か判定（ray counting）
  3. 内側のストランド → 現在の弧長に関わらず `target_m` にスケール（短ければ延長、長ければ短縮）
  4. 外側のストランド → 変更なし
- **用途**: 保護プリミティブ内側の毛を N cm に揃える（床屋の下から順次カット手順に対応）

### 6. Urchin Reset
- **入力**: なし
- **処理**: `_mesh_ops.urchin_reset(obj)`
- **動作**: 各ストランドを point[0]→point[1] 方向（毛包法線）に等間隔再配置。弧長保持。
- **用途**: シミュレーションや等比収縮後の歪みリセット → 再シミュレーション

---

## 標準作業手順（ユーザー確立済み）

```
1. Plant Hair (α=27, β=0.3, Empty配置)
   ↓
2. Extend (N=30 → 30cmウニ)
   ↓
3. Simulate (N=20 → 自然な垂れ)
   ↓
4. Mesh Shrink (球or平面で高さカット/丸カット)
   ↓
5. Mesh Shrink (前髪ラインをPlaneで)  ← 複数回OK
   ↓
6. Urchin Reset (等比収縮の歪み除去)
   ↓
7. Simulate (N=20 → 最終仕上げ)
   ↓
8. Blender スカルプト (Hair Brush で細部)
```

---

## 重要な地雷・注意事項

### Taichi 地雷（_sim_taichi.py を触る場合）
1. **`from __future__ import annotations` 禁止** → PEP 563 がカーネル型注釈を文字列化 → コンパイル失敗
2. **`@ti.kernel` の引数はスカラーのみ** → ndarray は `field.from_numpy()` / `to_numpy()` 経由
3. **カーネル内条件分岐**: `ti.select(cond, a, b)` を使う（if/else 不可）
4. **キャッシュ問題**: pyc 削除では解決しない。必ずアンインストール→再インストール

### Blender 5.1 地雷
- **ExportHelper / ImportHelper 禁止** → `context.window_manager.fileselect_add(self)` を使う
- **CURVE タイプは BVH 不可** → Plane/Sphere 等 MESH タイプのみ Shrink/Extend で使える
- **`surface_uv_coordinate` 属性**: スカルプト Add ブラシで自動生成されるが、空の Curves オブジェクトには存在しない → `_spiral_plant.py` で自動作成済み

### Mesh Shrink/Extend の座標系
- **交差判定**: 必ず `evaluated_get(deps)` の world 座標を使う（Surface Deform modifier込み）
- **書き戻し**: ローカル座標に scale-from-root で書く（スケールは無次元なので modifier 補正不要）

---

## バージョン履歴（Tokoya）

| バージョン | コミット | 内容 |
|---|---|---|
| v0.1.1 | f81b435 | Katsura からリネーム fork |
| v0.2.0 | 0966efd | 床屋アーキテクチャ完成（バッファ・ハンドラ削除、新ファイル追加） |
| v0.2.1 | f80e608 | pick_ref オペレーター（スポイトボタン） |
| v0.2.2 | cfefb86 | surface_uv_coordinate 欠損バグ修正 |
| v0.2.3 | e59a4c0 | mesh_shrink/extend 座標系バグ修正（evaluated使用、双方向レイキャスト） |
| v0.2.4 | 9d55c72 | CURVE タイプのエラーメッセージ改善 |
| v0.2.5 | f6efff8 | mesh_shrink: 閉じたメッシュの2重交差で最小弧長を選ぶ |
| **v0.2.6** | **未コミット** | **Simulate 保護機能 + Mesh Extend 仕様変更（内側N cm統一）** |

---

## 未解決 / 次回持ち越し

### v0.3 系 開発方針（2026-06-20）

以下は机上で確定させず、Blender上で実際に作成・実行・観察して仕様を決める。
推測だけでTaichi物理や操作感を決めない。

#### 実施順序

1. **UVペイントによる植毛範囲・長さ制御**
2. **根元が密、毛先が疎になる非等間隔関節**
3. **毛根をコライダー表面から0.5 mm外側へ配置**
4. **Taichi計算の調整**（1〜3の実動作確認後に仕様決定）

UV方式がないと他の変更を目的のヘアスタイルで評価できないため、必ず1から着手する。

#### UVペイント方式

- Head SkinのUVを利用した専用ペイント画像を用意する。
- 初期状態は白。
- **黒く塗った場所を毛の対象領域**とする（白地に毛の部分を黒く描く）。
- グレースケール値は毛の長さとして使用する。白=0 cm、黒=最大長。
- 例: 最大20 cmの場合、黒量255は20 cm、黒量約125は約10 cm。
- 計算は `length = (255 - pixel_value) / 255 * max_length`。
- 灰色は密度ではなく長さを決める。植毛本数・配置密度の仕様は別に検証する。
- Photoshop運用を想定するが、最初にBlender MCPとTexture Paintで実験する。
- `Create Head Mask`ボタンでCurvesのSurfaceからHeadマテリアル領域を抽出する。
- 作成物は`Tokoya_HairMask`、スケール1、白い2048px Non-Color画像。
- 元Head表面から法線方向へ0.5 mm離し、作成後はTexture Paint対象として選択する。
- 作成したマスクをRef Objectへ自動設定する。
- Density、Length、画像解像度、補間方法、閾値などの最終仕様は実画像で試してから決める。
- 既存のVogel螺旋植毛との統合・置換方法も実験結果を見て決める。

#### 非等間隔関節

- 等間隔関節によって長い毛が頭頂部で折れて見える問題を解消する。
- 毛根側は関節を密にし、毛先へ向かうほど疎にする。
- 長い毛は8関節以上を目標とする。
- 点数、分布式、長さ別の関節数、XPBD剛性補正は実際に動かして決める。
- Extend、Urchin Reset、静止長、曲げ拘束との整合性を実機確認する。
- 2026-06-20 MCP試験: 9点・8関節、累積位置 `t^1.7` を採用。
- 20 cm毛の区間長は根元から約4.6, 10.4, 14.9, 18.9, 22.5, 25.9,
  29.1, 32.2 mm。毛先区間は根元区間の約7倍。
- 4,000本で36,000点を生成し、MCP上で反映を確認。
- v0.3.0のUVマスク植毛へ実装。固定8点前提の既存機能は別作業。

#### 毛根の0.5 mmオフセット

- 毛根がコライダー表面に接して初期化されることで、ソルバーが爆発する問題への対策。
- 毛をコライダー表面の法線方向へ0.5 mm外側から生やす案を試す。
- 評価済みメッシュ、ワールド法線、固定点、コリジョン半径との関係を実機確認する。
- 0.5 mmは現時点の試験値であり、最終値はシミュレーション結果で決める。

#### スケール

- Head用ペイントメッシュと生成先Curvesはスケール1で扱う。
- 0.01スケールのままローカル座標へ長さを書き込むと、指定長の0.01倍になる問題がある。
- 既存キャラクターの0.01階層から独立させる場合は、見た目のワールド寸法を維持してスケールを適用する。

#### Taichi調整

- 小規模変更を予定しているが、現時点では仕様を決めない。
- UV方式、関節配置、毛根オフセットが動作してから検討する。

#### バージョン・配布物

- `v0.3.0` から `dist` にZIPを作成する。
- 最後の数字をビルド番号として扱う。
- ZIPを作成するたびにビルド番号を必ずインクリメントし、同じ番号を再利用しない。

### v0.3.1 UI整理

- Empty基準の旧Vogel植毛を削除し、`_spiral_plant.py`も削除。
- Body Meshを明示選択する。これはアニメーション追従Surface兼コライダー。
- Cutter MeshはMesh Shrink専用としてBody Meshと分離。
- 汎用`N`を削除し、`Simulation Steps`へ置換。
- ExtendとMesh ExtendをUI・Operator・`_mesh_ops.py`から削除。
- Hair Removeを追加。Curvesオブジェクト、Surface、UV Map、Modifierは維持し、
  ストランドだけを全削除する。
- 長さを変更する場合はHair Remove後、Max Lengthを変更してPlant Hairを再実行する。
- Mesh ShrinkとUrchin Resetは残す。`_mesh_ops.py`は9点ストランドへ更新。
- SimulateはMCP試験で、36,000点を旧8点で割って4,500本と誤認する問題を確認。
- Taichiソルバー本体は可変PPSと区間ごとの静止長に対応済みだったため、
  `_world_passthrough.py`を9点へ更新して4,000本として処理する。
- MCP再試験: 1ステップと20ステップの両方で成功。4,000本・36,000点を維持し、
  NaN/Infなし、根元2点固定、最大セグメント長約4.09 cm。
- 20ステップ後に毛が頭部から自然に下がることをViewportでも確認。

### v0.3.2 マージン変更

- Head Maskの植毛開始面をBody表面から法線方向へ1.0 mm外側にする。
- Body衝突マージンを5.0 mmから0.5 mmへ変更する。
- 毛根開始位置を衝突マージンより0.5 mm外側に確保する。
- v0.3.2はZIP作成のみ。ユーザー指示によりインストールとBlender実行テストは禁止。

### v0.3.3 Body衝突試行記録（同じ地雷を踏まないこと）

#### 発見した問題

1. **8点/9点の不一致**
   - 36,000点を旧8点で割ると、4,000本を4,500本として誤認した。
   - 割り切れるためエラーにならず、間違ったストランド境界で計算された。
   - `_mask_plant.POINTS_PER_STRAND`、`_mesh_ops._PPC`、
     `_world_passthrough.POINTS_PER_STRAND`は必ず同じ値にする。

2. **Body BVHの座標系不一致**
   - `BVHTree.FromObject()`で作ったBVHはBodyローカル座標だった。
   - 毛は評価後ワールド座標で計算していたため、衝突判定がほぼ発火しなかった。
   - CC Bodyは親Armatureによるworld scale 0.01を持つため、差が約100倍になった。
   - Bodyの評価済み頂点を`matrix_world`でワールド座標へ変換し、
     `BVHTree.FromPolygons(world_vertices, polygons)`で作ること。

3. **到着点だけの衝突判定はトンネリングする**
   - サブステップ中に点が表面を通過して反対側へ到達すると、
     到着点だけの最近傍判定では見逃す。
   - 前位置から予測位置までレイキャストするスイープCCDが必要。

4. **関節点だけでは不十分**
   - 両端の点がBody外側でも、長い関節間セグメントがBodyを横切る。
   - 各毛の全8セグメントも毎サブステップ検査する。

5. **衝突補正を速度へ変換すると反発する**
   - 旧式は`velocity = (corrected_position - previous_position) / dt`。
   - 数cmの押し戻しが大きな外向き速度になり、スプリングと組み合わさって
     毛が上空へ跳ねた。
   - 衝突前の物理予測位置から速度を計算し、衝突補正移動を速度へ加えない。
   - 接触時は内向き法線速度だけを除去し、接線速度は維持する。
   - 質量変更ではこの問題を直接解決できない。

6. **セルフコリジョン**
   - Tokoyaには毛同士のセルフコリジョン処理は存在しない（OFF）。
   - 計算負荷と不安定化の危険が大きいため、明示的な仕様変更なしに追加しない。

#### 採用したBody衝突方式

- Taichi XPBDの予測・スプリング計算はCUDAを使用。
- UIでCUDA（既定）/ Vulkan / CPUを選択可能。Backend変更時は
  `ti.reset()`してSolver classとFieldを再生成する。
- Bodyは選択された評価済みMeshからワールド座標BVHを毎Simulation開始時に作る。
- 各サブステップ:
  1. CUDAで予測位置とスプリング拘束を計算。
  2. 衝突前予測位置から物理速度を計算。
  3. 前位置→予測位置の点スイープCCD。
  4. 表面近傍点を0.5 mm外側へ投影。
  5. 毛の全セグメントを検査し、交差時は毛先側点を0.5 mm外側へ戻す。
  6. 内向き法線速度だけを除去。
  7. 衝突補正位置と補正済み速度を次サブステップへ渡す。

#### MCP最終試験

- 4,000本、9点/本、合計36,000点。
- CUDA、30 steps、8 substeps、20 iterations。
- 点スイープCCD: 3,465回。
- 近傍投影: 106,477回。
- セグメント拘束: 4,003回。
- 内向き法線速度除去: 111,367回。
- 全32,000セグメントの最終検査でBody貫通0。
- 影響ストランド0、NaN/Infなし、上方向へ跳ねた毛先0。
- Viewportで自然に垂れ、ユーザー確認PASS。

### v0.3.4 接触後の拘束再調整

- v0.3.3ではセグメント交差時に毛先側点だけを接触位置へ移動していた。
- 補正直後のセグメント長が崩れ、次サブステップのスプリングが急に回収すると
  再反発する可能性が残った。
- v0.3.4では交差位置の線形比率と固定/自由状態に応じ、接触補正を両端へ
  質量加重分配する。
- 最初の衝突処理後に「スプリング拘束1回→近傍・セグメント衝突1回」を
  4回交互に実行する。スプリングを4回まとめた後に衝突を1回だけ行う方式は、
  MCP試験で69セグメントの交差が残ったため不採用。
- 両端分配だけでも30ステップ後に75セグメントの微小交差が残った。
  最後に速度へ影響しない毛先側点の安全投影を最大4回行い、
  形状調整後の残留交差だけを除去する。
- MCPの300秒上限で30ステップ呼び出しがタイムアウトした状態を監査すると
  54セグメント残っていた。Simulation全体の終了後にも最大8回（内部4パス）
  の最終安全監査を追加し、速度を変えずに残留交差を除去する。
- 反発係数は0。衝突補正量は速度へ加えず、内向き法線速度だけを除去する。
- 公開説明: `Tokoya`は日本語の「床屋」、英語では`barber`を意味する。

### 確定している次の作業
- Head Skin UVを使った白地・黒描画のペイントマスク実験。
- 実験成功後にUV方式の実装仕様を決める。

### ユーザーが寝ながら考えること
- 追加ボタンのアイデア（現状6ボタン、10個まで余裕あり）

### 候補アイデア（未確定）
- **長さ情報表示** — 平均・最大・最小長さを表示するボタン
- **領域選択カット** — Empty 近傍だけ操作（部分カット）
- **ランダム変化** — 長さに±X%のランダムゆらぎ
- **旋毛位置のQuickSet** — 前回の Empty 座標を一発再現

### 旋毛テストデータ（要確認）
- α=27cm、β=0.3cm、Empty名=「エンプティ」
- **Empty の正確な世界座標は未取得**（次回 MCP 接続時に読む）
  ```python
  import bpy
  for o in bpy.data.objects:
      if o.type == "EMPTY":
          print(o.name, list(o.matrix_world.translation))
  ```

---

## MCP クイックリファレンス（Tokoya 用）

```python
# 現状確認
import bpy
curves = [o for o in bpy.data.objects if o.type == "CURVES"]
print(len(curves), "Curves objects")

# 植毛テスト（エンプティが選択されている状態で）
import bpy
wm = bpy.context.window_manager
wm.tokoya_ref_obj = "エンプティ"
wm.tokoya_alpha = 27.0
wm.tokoya_beta = 0.3
bpy.ops.tokoya.plant_hair()

# Extend テスト
wm.tokoya_n = 30.0
bpy.ops.tokoya.extend()

# Simulate テスト
wm.tokoya_n = 20
bpy.ops.tokoya.simulate()
```

---

## ブランチ地図

```
* vbd-features-applied  f6efff8  Tokoya v0.2.5 (現在)
  main (Katsura)        7e7f63a  Phase 7W-G frozen — 触らない
```

origin への push はユーザー未承認。

---

## オーナー情報

Owner: `azoo` / `ysk424` (ysk424@hotmail.com)  
Communication: 主に日本語  
Platform: Windows 11, RTX 5070 Ti, Blender 5.1

---

## 2026-06-27 Tokoya v0.6.0 作業記録

- v0.6.0として、長髪向けの点数自動選択を実装した。
  - `points = clamp(9 + floor((Max Length cm - 20) / 10), 9, 13)`
  - 60 cmでは13点/strand。
- 植毛時の点配置をNatural Root Spacingへ変更した。
  - 最大長の毛は比率`1.22`の等比配置。
  - 短い毛は最長毛基準の根元2セグメントを共有し、残りを均等割り。
  - Root Zoneより短い毛は全体を圧縮。
- `Mesh Shrink`は可変点数対応にした。
  - 交差判定は従来通りevaluated worldで行う。
  - 切れた毛だけを現在カーブ上でNatural Root Spacingに再サンプリングする。
  - Mesh ShrinkはUNI化しない。
- `Urchin Reset` / UI表示上のUNI不具合を修正した。
  - 以前はローカル座標で直線化していたため、Surface Deform後の表示では一部が曲がって残った。
  - 修正後はevaluated worldで直線化し、点ごとのSurface Deform offsetを引いてローカルへ書き戻す。
  - MCP確認では6000本、13点/strand、evaluated表示の最大直線誤差は約0.00045 mm、0.01 mm超の残り0本。
- Hair RemoveとREC/Animation録画機能を削除した。
  - `_recording.py`を削除。
  - Animationパネルは空にした。
  - 静的な`Simulate`は、長さを見るための重力落下用途として維持。
- `dist/tokoya-0.6.0.zip`を作成した。
- MCPは最後に切断されたため、Codex側から`.blend`保存はできなかった。ユーザー側で終了処理中。
