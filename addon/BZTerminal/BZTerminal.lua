-- BZ Terminal : prix de l'HV dans les infobulles.
-- Données : BZT_DATA (Data.lua), régénéré toutes les heures par GitHub Actions et
-- téléchargé par le lanceur. Un /reload charge la dernière version.
--
-- BZT_DATA.houses[key] = { name, faction, ts, items = { [itemID] = {min, med, med7, sold24, minPrev} } }
-- (prix en pièces de cuivre, par unité)

local TITLE = "|cffffa028BZ Terminal|r"
local GREY, GREEN, RED = "|cff808080", "|cff3ddc84", "|cffff4d4d"
local DEAL_RATIO = 0.7 -- prix min <= 70 % de la médiane 7j => affaire

local house

-- Icônes de pièces du jeu (or, argent, cuivre)
local GOLD   = "|TInterface\\MoneyFrame\\UI-GoldIcon:0:0:2:0|t"
local SILVER = "|TInterface\\MoneyFrame\\UI-SilverIcon:0:0:2:0|t"
local COPPER = "|TInterface\\MoneyFrame\\UI-CopperIcon:0:0:2:0|t"

local function money(c)
  if not c then return GREY .. "—|r" end
  c = floor(c + 0.5)
  local g, s, cu = floor(c / 10000), floor(c % 10000 / 100), c % 100
  if g >= 100 then return g .. GOLD end
  if g > 0 then return format("%d%s %02d%s", g, GOLD, s, SILVER) end
  if s > 0 then return format("%d%s %02d%s", s, SILVER, cu, COPPER) end
  return cu .. COPPER
end

local function ageText(ts)
  local m = floor((time() - ts) / 60)
  if m < 0 then m = 0 end
  if m < 60 then return m .. " min" end
  return format("%d h %02d", floor(m / 60), m % 60)
end

local function pickHouse()
  if type(BZT_DATA) ~= "table" or type(BZT_DATA.houses) ~= "table" then return nil end
  local faction, first = UnitFactionGroup("player"), nil
  for _, h in pairs(BZT_DATA.houses) do
    first = first or h
    if h.faction == faction then return h end
  end
  return first
end

local function addPrices(tooltip, itemID)
  if not itemID then return end
  house = house or pickHouse()
  if not house then return end
  local e = house.items[itemID]
  if not e then
    tooltip:AddDoubleLine(TITLE, GREY .. "pas en vente à l'HV|r")
    tooltip:Show()
    return
  end
  local mn, med7, sold, prev = e[1], e[3], e[4], e[5]

  local chg = ""
  if mn and prev and prev > 0 and mn ~= prev then
    local p = (mn / prev - 1) * 100
    chg = format("  %s%+.1f%%|r", p >= 0 and GREEN or RED, p)
  end
  tooltip:AddDoubleLine(TITLE, GREY .. "il y a " .. ageText(house.ts) .. "|r")
  tooltip:AddDoubleLine("Prix min", money(mn) .. chg, 1, 1, 1, 1, 1, 1)
  if med7 then
    tooltip:AddDoubleLine("Médiane 7j", money(med7), 1, 1, 1, 1, 1, 1)
  end
  if sold and sold > 0 then
    tooltip:AddDoubleLine("Ventes 24h (est.)", sold, 1, 1, 1, 1, 1, 1)
  end
  if mn and med7 and med7 > 0 and mn <= med7 * DEAL_RATIO then
    tooltip:AddLine(format("%sAffaire : %d%% sous la médiane 7j|r", GREEN, floor((1 - mn / med7) * 100 + 0.5)))
  end
  tooltip:Show()
end

local function itemIDFromTooltip(tooltip, data)
  if data and data.id then return data.id end
  local _, link = tooltip:GetItem()
  return link and tonumber(link:match("item:(%d+)"))
end

-- Accroche des infobulles : API moderne si disponible, sinon méthode classique
if TooltipDataProcessor and Enum and Enum.TooltipDataType then
  TooltipDataProcessor.AddTooltipPostCall(Enum.TooltipDataType.Item, function(tooltip, data)
    if tooltip ~= GameTooltip and tooltip ~= ItemRefTooltip then return end
    if tooltip.IsForbidden and tooltip:IsForbidden() then return end
    addPrices(tooltip, itemIDFromTooltip(tooltip, data))
  end)
else
  for _, tt in ipairs({ GameTooltip, ItemRefTooltip }) do
    tt:HookScript("OnTooltipSetItem", function(self) addPrices(self, itemIDFromTooltip(self)) end)
  end
end

-- Commandes : /bz  et  /bz affaires
local function itemLabel(id)
  local getInfo = (C_Item and C_Item.GetItemInfo) or GetItemInfo
  local _, link = getInfo(id)
  return link or ("Objet #" .. id)
end

local function status()
  house = house or pickHouse()
  if not house then
    print(TITLE .. " : aucune donnée. Ouvre le lanceur BZ Terminal, puis fais /reload.")
    return
  end
  local n = 0
  for _ in pairs(house.items) do n = n + 1 end
  print(format("%s : %s, %d objets, données d'il y a %s.", TITLE, house.name or "?", n, ageText(house.ts)))
  if time() - house.ts > 2 * 3600 then
    print(TITLE .. " : données de plus de 2 h. Fais /reload ; si ça persiste, ouvre le lanceur BZ Terminal.")
  end
end

local function deals()
  house = house or pickHouse()
  if not house then return status() end
  local list = {}
  for id, e in pairs(house.items) do
    local mn, med7, sold = e[1], e[3], e[4]
    if mn and med7 and med7 > 0 and sold and sold > 0 and mn <= med7 * DEAL_RATIO then
      list[#list + 1] = { id = id, mn = mn, med7 = med7, r = mn / med7 }
    end
  end
  table.sort(list, function(a, b) return a.r < b.r end)
  if #list == 0 then
    print(TITLE .. " : pas d'affaire repérée pour l'instant (il faut quelques jours d'historique).")
    return
  end
  print(TITLE .. " : meilleures affaires (prix min vs médiane 7j)")
  for i = 1, math.min(10, #list) do
    local d = list[i]
    print(format("  %s  %s  %s-%d%%|r", itemLabel(d.id), money(d.mn), GREEN, floor((1 - d.r) * 100 + 0.5)))
  end
end

SLASH_BZTERMINAL1 = "/bz"
SlashCmdList.BZTERMINAL = function(msg)
  msg = (msg or ""):lower()
  if msg:find("^aff") or msg == "deals" then deals() else status() end
end

local f = CreateFrame("Frame")
f:RegisterEvent("PLAYER_LOGIN")
f:SetScript("OnEvent", function()
  house = pickHouse()
  status()
end)
