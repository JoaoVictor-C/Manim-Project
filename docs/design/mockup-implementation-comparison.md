# Design mockups vs. implementation

I compared all nine design screens in `docs/design/mockups/project` with the implemented UI source under `src/manim_studio/ui`. This report also includes a screenshot comparison of Compose. The remaining screens are compared from source because matching running-app screenshots were not supplied.

## Differences by screen

- **Main / Compose** — Both screenshots show Layers, Stage, Properties, and Timeline in Compose, but the actual screenshot has a different project/selection and a materially different arrangement. The mockup has a compact stage with its own left tool rail and transport, layer add/presets controls, an object selected with transform handles, and a detailed multi-lane timeline. The actual screenshot shows a large black preview, Scene properties, a nested Pythagorean layer tree, and a timeline dominated by empty tracks with one visible clip. See [Main mockup](mockups/project/Main.dc.html) and [Compose page](../../src/manim_studio/ui/pages/compose.py).

- **Animate** — The mockup puts the curve editor beside the preview, above the timeline. The implemented page uses a separate Curves/Graph panel and timeline arrangement. Its graph includes a curve legend, recording control, and frame-keys action; these controls aren’t represented in the mockup. See [Animate mockup](mockups/project/Animate.dc.html) and [Animate page](../../src/manim_studio/ui/pages/animate.py).

- **Audio** — The mockup centers on a timeline with track controls, a mixer, voice-generation controls, subtitle cues, and pronunciation mapping. The implemented page organizes Mix, Sounds, Subtitles, and Narration as cards and tables, with audio lanes and a level meter. The layout and the way these controls are grouped differ from the mockup. See [Audio mockup](mockups/project/Audio.dc.html) and [Audio page](../../src/manim_studio/ui/pages/audio.py).

- **Code** — The mockup shows a multi-column workspace: project explorer, editor, preview, chapters, and output/values panels. The implementation has separate code-workspace components, but the mockup’s exact screen arrangement and sample content are not the implemented page’s fixed layout. See [Code mockup](mockups/project/Code.dc.html) and [Code page](../../src/manim_studio/ui/pages/code.py).

- **Deliver** — The mockup puts export choices, output settings, estimate, render queue, and completed jobs together in one screen. The implemented export flow uses an export dialog and queue components; the mockup’s exact card arrangement and example queue state are illustrative rather than a one-to-one layout. See [Deliver mockup](mockups/project/Deliver.dc.html), [Export dialog](../../src/manim_studio/ui/deliver/export_dialog.py), and [Queue view](../../src/manim_studio/ui/deliver/queue_view.py).

- **Components** — This is a component showcase containing example buttons, fields, navigation, rows, clips, menus, and a code-execution confirmation dialog. It is not a standalone app page. The implementation has corresponding controls and dialogs across multiple modules, but the showcase’s examples and exact styling/layout are not a screen-by-screen match. See [Components mockup](mockups/project/Components.dc.html).

- **Foundations** — This is a design-system specification for colors, type, spacing, and motion, not an app screen. It describes intended tokens and principles; verifying exact token-by-token differences would require comparing the entire mockup stylesheet with the theme definitions. See [Foundations mockup](mockups/project/Foundations.dc.html) and [theme source](../../src/manim_studio/ui/style/theme.py).

- **Light** — The HTML file is only a light-theme label and does not contain a complete screen to compare. See [Light mockup](mockups/project/Light.dc.html).

- **Palette** — The mockup shows a command palette with example search results and actions. The implementation has a command palette, but the mockup’s sample results and state are static; they can’t be treated as a guaranteed live-content match. See [Palette mockup](mockups/project/Palette.dc.html) and [palette implementation](../../src/manim_studio/ui/shell/palette.py).

- **Welcome** — The mockup includes template cards and a recent-project list with specific example names and timestamps. The implementation has a welcome screen and new-project flow, but those example entries and their exact presentation are mockup content. See [Welcome mockup](mockups/project/Welcome.dc.html) and [Welcome implementation](../../src/manim_studio/ui/shell/welcome.py).

## Differences across screens

- The mockups use a single desktop window with a shared top bar and status bar. The app uses a shared shell, but its pages rearrange or relocate controls to fit each page’s workflow.
- Mockup text, selections, and status are fixed examples—for example, “Euler’s identity,” selected objects, render progress, and error messages. Those are not persistent UI content in the implementation.
- The mockups use HTML/CSS styling and illustrative artwork. The app uses Qt widgets and its own theme and layout code. Fonts, spacing, gradients, borders, and control dimensions may differ even where the same feature exists.

## Scope of this comparison

For the other screens, this remains a source-based comparison; rendered screenshot comparisons were not supplied.

## Compose screenshot comparison

The first supplied screenshot is the target design (the Euler identity scene); the second is the running app (the Pythagorean scene). Content differs, so this comparison focuses on workspace layout and controls rather than artwork or project-specific layer names.

- **Workspace proportions:** The design uses a narrow Layers column, a broad center workspace, and a compact Properties column. The actual app gives Properties substantially more width and the center workspace is dominated by a taller, near full-width preview.
- **Stage presentation:** The design shows a contained 16:9 canvas on a dark dotted stage, with Follow playhead, Fit/75%/100%, and fullscreen controls in the stage header. The actual screenshot shows a black preview filling nearly all available center width; its header reports playback time, frame, render-ahead status, and Fit percentage. Keep those useful frame and ahead counters, while adding the target’s Follow playhead, Fit/75%/100%, and fullscreen controls to the header. The target has a vertical tool rail inside the stage and transport controls directly beneath the canvas; the actual has transport controls overlaid at the bottom of the preview and no visible tool rail in this screenshot.
- **Video player:** The target player is a compact floating pill centered below the canvas, with start, play, end, time, repeat, speed, and volume controls. The actual player is wider and overlaid near the bottom of the preview; it has different spacing and lacks the visible volume control. Match the target’s compact spacing and placement, and add the volume button (the mockup places it at the right end of the player).
- **Properties tabs and context:** The target inspector has three top-level tabs—Properties, Clip, and Scene—and shows Properties for a selected text object, including Auto-key, transform, opacity, appearance, per-part colors, editable source text, size, and Split into parts. The actual screenshot shows Scene properties because no object is selected, including scene length, grow-with-content, dimensions, frame rate, background, morph mode, and camera controls. Preserve those scene controls under Scene, and provide the target’s object and clip inspectors under Properties and Clip. Compare with an object selected before treating every missing field as an implementation gap.
- **Layers panel:** The design has an 8-layer count, a plus button and “…” menu in the header, eye visibility controls on rows, type badges, and a prominent centered Add object button plus Presets in the footer. The actual screenshot has a different tree with expanded child rows, disclosure arrows, and footer actions for Add, grouping, delete, and reorder. Its Add action is not the same prominent centered Add object action.
- **Timeline controls and tracks:** The design includes Snap and Auto-key indicators, + Clip, zoom controls, and tracks for the three visible text layers plus Subtitles and Narration. Its clips are colored by action/type and include keyframe diamonds. The actual screenshot shows only a Subtitles row and a nested layer/property hierarchy, with a single orange “Circumscribe” clip and otherwise empty tracks; Snap, Auto-key, + Clip, and the target zoom slider are not visible. Keep useful existing timeline elements while adding these target controls.
- **Ruler and playhead:** The design labels whole seconds across the visible range and shows the playhead at 2.40 s. The actual ruler uses half-second ticks over a 5-second scene and the playhead is at 2.87 s. This partly follows the different scene and playback state, but the scale and tick density are also visibly different.
- **Top bar:** Both show navigation and command search. The actual bar includes undo/redo and command search, but the navigation/search spacing and alignment differ. The target’s page-specific stage and timeline controls are distributed across those panels rather than the global bar.
- **Visual finish:** Both use a dark theme, rounded cards, and blue/purple accents. The actual screenshot has denser/smaller labels, more visible outlines and separators, a flatter black preview, and different spacing and panel borders than the target.

## Remaining visual work

Implementation status (2026-10-30): Stage Fit/75%/100% and fullscreen controls, the render/frame readout, volume toggle, Timeline Snap/Auto-key/+ Clip/zoom controls, Layers count/+ /… header and Add object/Presets footer, Properties/Clip/Scene inspector tabs, per-layer visibility, and the vertical Select/Hand/Text/Shape/Anchor rail are implemented. The center canvas is constrained to leave a pasteboard around the frame, and the initial side-panel proportions were adjusted. The remaining work is visual tuning against equivalent running-app states; the supplied running-app screenshot predates these controls and uses a different project.

1. **Compare equivalent Compose states.** Load a project with a selected text layer, several clips, subtitles, and narration. Match the window size, zoom, playhead time, and selection before comparing screenshots. Check empty-project and scene-selected states separately.
2. **Tune panel geometry and styling.** Compare splitter proportions, minimum widths, panel padding, row height, label size, separators, control outlines, corner radius, and accent use against the target. Repeat at a smaller window size to check that the layout remains usable.
3. **Review Stage and timeline density.** With equivalent content loaded, check the canvas framing, transport placement, ruler tick density, and legibility of empty lanes. Keep the playhead label, ruler, and transport time readout synchronized.
