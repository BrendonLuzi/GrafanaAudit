import pandas as pd
import streamlit as st

st.set_page_config(page_title="Grafana Audit", layout="wide")

st.title("Grafana Audit")

MAIN_ORG = "Main Org."
CATEGORIES = ["Enterprise Active", "Enterprise Inactive", "Non Enterprise"]

# OPTIONAL: Define org-to-category mappings here if not present in either CSV.
ORG_CATEGORY_MAP = {}


# 1. Load Primary Data & Audit Descriptions
@st.cache_data
def load_data():
    df_users = pd.read_csv("grafana_user_orgs.csv")
    df_users.columns = df_users.columns.str.strip()

    # Clean Org IDs in user df
    if "org_id" in df_users.columns:
        df_users["org_id"] = (
            df_users["org_id"].fillna("").astype(str).str.strip()
        )

    desc_map = {}
    df_desc = None
    try:
        df_desc = pd.read_csv("org_descriptions.csv")
        df_desc.columns = df_desc.columns.str.strip()

        # Clean Org IDs & descriptions in desc df
        if "org_id" in df_desc.columns and "description" in df_desc.columns:
            df_desc["org_id"] = (
                df_desc["org_id"].fillna("").astype(str).str.strip()
            )
            df_desc["description"] = df_desc["description"].fillna("").astype(str)
            desc_map = df_desc.set_index("org_id")["description"].to_dict()
    except FileNotFoundError:
        pass
    except Exception as e:
        st.warning(f"⚠️ Note reading `org_descriptions.csv`: {e}")

    return df_users, df_desc, desc_map


df, df_desc, org_desc_map = load_data()

all_users = set(df["user_id"])
unique_orgs = sorted(df["org_name"].unique())

# Extract Org IDs as Clean Strings
if "org_id" in df.columns:
    org_to_id = df.set_index("org_name")["org_id"].to_dict()
else:
    org_to_id = {org: str(idx + 1) for idx, org in enumerate(unique_orgs)}

# Build Org Category Dictionary
org_to_cat = {}
if "category" in df.columns:
    org_to_cat.update(df.set_index("org_name")["category"].to_dict())

if df_desc is not None and "category" in df_desc.columns:
    desc_cat_map = df_desc.set_index("org_id")["category"].to_dict()
    for org_name in unique_orgs:
        o_id = org_to_id.get(org_name, "")
        if o_id in desc_cat_map:
            org_to_cat[org_name] = desc_cat_map[o_id]

# Fill missing mappings
for org in unique_orgs:
    if org not in org_to_cat or pd.isna(org_to_cat[org]):
        org_to_cat[org] = ORG_CATEGORY_MAP.get(org, "Non Enterprise")

# Team orgs excluding Main Org
functional_df = df[df["org_name"] != MAIN_ORG]
eval_orgs = [o for o in unique_orgs if o != MAIN_ORG]

# Active team users
active_team_users = set(functional_df["user_id"])
main_only_users = all_users - active_team_users

# Group mappings
user_functional_orgs = (
    functional_df.groupby("user_id")["org_name"].apply(set).to_dict()
)
org_user_sets = df.groupby("org_name")["user_id"].apply(set).to_dict()

# 2. Session State Setup
if "selected_orgs" not in st.session_state:
    st.session_state.selected_orgs = set()

if "ms_key" not in st.session_state:
    st.session_state.ms_key = []

if "sort_by" not in st.session_state:
    st.session_state.sort_by = "Org ID"

if "sort_ascending" not in st.session_state:
    st.session_state.sort_ascending = True

if "inspect_org_select" not in st.session_state:
    st.session_state.inspect_org_select = unique_orgs[0] if unique_orgs else ""


# 3. Synchronized Callbacks
def sync_from_multiselect():
    st.session_state.selected_orgs = set(st.session_state.ms_key)


def sync_from_editor():
    edited_rows = st.session_state.editor_key.get("edited_rows", {})
    search_term = st.session_state.get("table_search", "").lower()
    selected_cats = st.session_state.get("cat_filter", CATEGORIES)

    visible_df = get_display_df(search_term, selected_cats)

    for row_idx, changes in edited_rows.items():
        org_name = visible_df.iloc[row_idx]["Organization"]
        clean_org_name = org_name.replace(" (Ignored)", "")

        if "Inspect Notes?" in changes and changes["Inspect Notes?"]:
            st.session_state.inspect_org_select = clean_org_name

        if "Mark for Removal" in changes:
            if clean_org_name == MAIN_ORG:
                continue

            if changes["Mark for Removal"]:
                st.session_state.selected_orgs.add(clean_org_name)
            else:
                st.session_state.selected_orgs.discard(clean_org_name)

    st.session_state.ms_key = sorted(list(st.session_state.selected_orgs))


def clear_all_callback():
    st.session_state.selected_orgs = set()
    st.session_state.ms_key = []
    if "editor_key" in st.session_state:
        del st.session_state["editor_key"]


def select_category_callback(target_category):
    target_clean = str(target_category).strip().lower()
    cat_orgs = set()

    for org in eval_orgs:
        cat_value = str(org_to_cat.get(org, "Non Enterprise")).strip().lower()
        if cat_value == target_clean or target_clean in cat_value:
            cat_orgs.add(org)

    st.session_state.selected_orgs.update(cat_orgs)
    st.session_state.ms_key = sorted(list(st.session_state.selected_orgs))

    if "editor_key" in st.session_state:
        del st.session_state["editor_key"]


# Set calculations
orgs_to_remove = st.session_state.selected_orgs
orgs_to_keep = set(eval_orgs) - orgs_to_remove

# Count remaining team orgs per active team user
user_kept_count = {
    u: len(user_functional_orgs[u] & orgs_to_keep) for u in active_team_users
}

# Users newly orphaned by current selections
newly_purged_users = {u for u, count in user_kept_count.items() if count == 0}
retained_team_users = active_team_users - newly_purged_users

# 4. Top Dashboard Metrics
col1, col2, col3, col4 = st.columns(4)
col1.metric("Total Users", len(all_users))
col2.metric(
    "Main Org. Only Users",
    len(main_only_users),
    help="Users with no assigned team orgs other than the Main Org. (baseline)",
)
col3.metric("Remaining Users", len(retained_team_users))

deleted_count = len(newly_purged_users)
col4.metric(
    "Users Migrated to Open Source",
    deleted_count,
    delta=f"-{deleted_count} removed" if deleted_count > 0 else None,
    delta_color="inverse",
)

st.divider()

# 5. Build Table Data
stats = []
current_inspect = st.session_state.get("inspect_org_select", "")

for org in unique_orgs:
    users_in_org = org_user_sets.get(org, set())
    cat = org_to_cat.get(org, "Non Enterprise")
    o_id = str(org_to_id.get(org, ""))
    raw_note = str(org_desc_map.get(o_id, "")).strip()

    is_currently_inspected = org == current_inspect

    if org == MAIN_ORG:
        purged_count = 0
        is_removed = False
        display_name = f"{org} (Ignored)"
    else:
        if org in orgs_to_keep:
            purged_count = sum(
                1 for u in users_in_org if user_kept_count.get(u, 0) == 1
            )
        else:
            purged_count = sum(
                1 for u in users_in_org if user_kept_count.get(u, 0) == 0
            )
        is_removed = org in orgs_to_remove
        display_name = org

    stats.append(
        {
            "Org ID": o_id,
            "Organization": display_name,
            "Category": cat,
            "Total Members": len(users_in_org),
            "Users Migrated with current selections": purged_count,
            "Inspect Notes?": is_currently_inspected,
            "Mark for Removal": is_removed,
            "_raw_note": raw_note,
        }
    )

full_df = pd.DataFrame(stats)


# 6. Sorting & Filtering Helper
def get_display_df(search_term="", selected_cats=None):
    if selected_cats is None:
        selected_cats = CATEGORIES

    df_out = full_df.copy()

    # Category Filter
    if selected_cats:
        df_out = df_out[df_out["Category"].isin(selected_cats)]

    # Search Term Filter
    if search_term:
        df_out = df_out[
            df_out["Organization"].str.contains(search_term, case=False)
            | df_out["Org ID"].astype(str).str.contains(search_term, case=False)
            | df_out["_raw_note"].str.contains(search_term, case=False)
        ]

    return df_out.sort_values(
        by=st.session_state.sort_by,
        ascending=st.session_state.sort_ascending,
    ).reset_index(drop=True)


# 7. UI Controls
st.subheader("Organizations Selection")
st.caption(
    "ℹ️ **Main Org. Note:** Ignored. Users belonging ONLY to Main Org are listed under 'Main Org. Only Users'."
)

# Search & Quick Select Bar
st.multiselect(
    "Search & Quick Select Organizations:",
    options=eval_orgs,
    key="ms_key",
    on_change=sync_from_multiselect,
    placeholder="Type to quick-add orgs to removal list...",
)

# Batch Action Buttons
st.markdown("### Batch Select All by Category")
b1, b2, b3, b4 = st.columns(4)

b1.button(
    "Select: Enterprise Active",
    on_click=select_category_callback,
    args=("Enterprise Active",),
)

b2.button(
    "Select: Enterprise Inactive",
    on_click=select_category_callback,
    args=("Enterprise Inactive",),
)

b3.button(
    "Select: Non Enterprise",
    on_click=select_category_callback,
    args=("Non Enterprise",),
)

b4.button("Clear All Selections", on_click=clear_all_callback)

st.markdown("---")

# Filters and Sort Controls
col_cat, col_search, col_sort_by, col_sort_dir = st.columns([3, 2, 2, 1])

with col_cat:
    selected_categories = st.multiselect(
        "Filter Display Category:",
        options=CATEGORIES,
        default=CATEGORIES,
        key="cat_filter",
    )

with col_search:
    search_term = st.text_input(
        "Filter Table View:",
        key="table_search",
        placeholder="Search org name, ID, or audit note...",
    )

with col_sort_by:
    st.session_state.sort_by = st.selectbox(
        "Sort Table By:",
        options=[
            "Org ID",
            "Organization",
            "Category",
            "Total Members",
            "Users Migrated with current selections",
            "Mark for Removal",
        ],
        index=0,
    )

with col_sort_dir:
    sort_dir = st.radio("Order:", options=["Asc", "Desc"], horizontal=True)
    st.session_state.sort_ascending = sort_dir == "Asc"

display_df = get_display_df(search_term, selected_categories)

# Hide internal search column from table render
render_df = display_df.drop(columns=["_raw_note"])

# 8. Interactive Data Table
st.data_editor(
    render_df,
    key="editor_key",
    on_change=sync_from_editor,
    hide_index=True,
    height=420,
    disabled=[
        "Org ID",
        "Organization",
        "Category",
        "Total Members",
        "Users Migrated with current selections",
    ],
    column_config={
        "Org ID": st.column_config.TextColumn("Org ID"),
        "Organization": st.column_config.TextColumn("Organization Name"),
        "Category": st.column_config.TextColumn("Category"),
        "Total Members": st.column_config.NumberColumn(
            "Total Members", help="Total users enrolled in this org"
        ),
        "Users Migrated with current selections": st.column_config.NumberColumn(
            "Users Migrated with current selections",
            help="Users who lose total team access if this org is deleted",
        ),
        "Inspect Notes?": st.column_config.CheckboxColumn(
            "Inspect?",
            help="Check this box to display this organization's audit rationale in the card below",
            default=False,
        ),
        "Mark for Removal": st.column_config.CheckboxColumn(
            "Migrate?",
            help="Check or uncheck to mark organization for deletion",
            default=False,
        ),
    },
)

# 9. Audit Rationale Inspector Card
st.markdown("---")
with st.container(border=True):
    st.markdown("### Organization Details")
    st.caption(
        "💡 **Tip:** Check the **'Inspect?'** box on any row in the table above to load its details here."
    )

    selected_inspect_org = st.selectbox(
        "Select Organization to inspect details:",
        options=unique_orgs,
        key="inspect_org_select",
    )

    inspected_id = str(org_to_id.get(selected_inspect_org, ""))
    inspected_cat = org_to_cat.get(selected_inspect_org, "Non Enterprise")
    inspected_note = org_desc_map.get(
        inspected_id, "No audit notes available for this organization."
    )

    if not inspected_note or inspected_note.strip() == "":
        inspected_note = "No audit notes available for this organization."

    st.info(
        f"**Organization:** {selected_inspect_org} (ID: `{inspected_id}`)\n\n"
        f"**Category:** `{inspected_cat}`\n\n"
        f"**Audit Rationale & Notes:**\n\n"
        f"{inspected_note}"
    )
